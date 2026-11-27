"""Gambit registry, detection and gambit-aware evaluation.

Rules this module enforces

* The sacrifice and normal main-line gambit moves are **never** blunders.
* Inside the gambit window a player's move is compared with the best
  *gambit-keeping* move (restricted root-move analysis), not with the global
  engine best — which would usually just say "decline the gambit".
* A move is a ``gambit_deviation`` only if it loses > threshold versus that
  reference, or drops far below the gambit's own baseline evaluation.
* When the *opponent* plays the gambit, their sacrifice is not an error; the
  player's replies are judged and trap-falls become ``defender_trap`` leaks.
* Dubious gambits the player chooses get one informational note, never a push
  away from the opening.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache

import chess

from app.config import DATA_DIR, get_settings
from app.tools import engine
from app.tools.openings import gambit_entries, lookup_position
from app.tools.pgn_utils import fen_key, material_balance, san_line_to_uci

GAMBITS_FILE = DATA_DIR / "gambits.json"
BASELINE_TOLERANCE_CP = 150  # "far below the baseline"


@dataclass(frozen=True)
class GambitDef:
    id: str
    name: str
    eco: str | None
    side: str  # the sacrificing side
    trigger_uci: tuple[str, ...]
    theory_end_ply: int
    objective_eval_cp: int | None  # White's POV
    soundness: str
    # fen_key -> set of theory moves (UCI) from every theory line
    theory_moves: dict[str, frozenset[str]] = field(default_factory=dict, hash=False, compare=False)

    @property
    def is_real(self) -> bool:
        return self.soundness != "not_a_real_gambit"


@dataclass
class GambitMatch:
    gambit: GambitDef
    played_by_user: bool  # True: the player sacrificed; False: the player defends
    window_end_ply: int
    detected_by: str  # "trigger" | "material+eco"


@dataclass
class GambitMoveVerdict:
    tag: str  # gambit_sacrifice | gambit_theory | ok | gambit_deviation | defender_trap
    loss_cp: int = 0
    reference_move: str | None = None
    reason: str = ""


@lru_cache(maxsize=1)
def registry() -> dict[str, GambitDef]:
    """Load the curated registry and index every theory move by position."""
    data = json.loads(GAMBITS_FILE.read_text(encoding="utf-8"))
    out: dict[str, GambitDef] = {}
    for g in data["gambits"]:
        theory: dict[str, set[str]] = {}
        lines = [g["trigger"], *g["theory_lines"]]
        for line in lines:
            board = chess.Board()
            for uci in san_line_to_uci(line):
                theory.setdefault(fen_key(board), set()).add(uci)
                board.push_uci(uci)
        out[g["id"]] = GambitDef(
            id=g["id"],
            name=g["name"],
            eco=g.get("eco"),
            side=g["side"],
            trigger_uci=tuple(san_line_to_uci(g["trigger"])),
            theory_end_ply=g["theory_end_ply"],
            objective_eval_cp=g.get("objective_eval_cp"),
            soundness=g["soundness"],
            theory_moves={k: frozenset(v) for k, v in theory.items()},
        )
    return out


def get(gambit_id: str) -> GambitDef | None:
    return registry().get(gambit_id)


def detect_gambit(moves_uci: list[str], color: str) -> GambitMatch | None:
    """Return the gambit this game follows, if any.

    1. Curated trigger prefix (longest trigger wins, e.g. Milner-Barry over French).
    2. Fallback: the player is >= 1 pawn down within the first 15 plies *and*
       the position is an ECO entry whose name contains "Gambit".
    """
    if not get_settings().respect_gambits:
        return None
    best: GambitDef | None = None
    for g in registry().values():
        n = len(g.trigger_uci)
        if n and tuple(moves_uci[:n]) == g.trigger_uci and (best is None or n > len(best.trigger_uci)):
            best = g
    if best is not None:
        if not best.is_real:
            return None
        return GambitMatch(best, played_by_user=(best.side == color), window_end_ply=best.theory_end_ply,
                           detected_by="trigger")

    # Fallback detection — never treat a mere material deficit as a gambit
    # unless theory confirms it.
    board = chess.Board()
    player = chess.WHITE if color == "white" else chess.BLACK
    for ply, uci in enumerate(moves_uci[:15], start=1):
        board.push_uci(uci)
        for side, sign in ((player, True), (not player, False)):
            if material_balance(board, side) <= -1:
                hit = lookup_position(board)
                if hit and "Gambit" in hit[1] and "Queen's Gambit" not in hit[1]:
                    gid = "eco_" + hit[1].lower().replace(" ", "_").replace(":", "").replace("'", "")
                    g = GambitDef(id=gid, name=hit[1], eco=hit[0], side="white" if side == chess.WHITE else "black",
                                  trigger_uci=tuple(moves_uci[:ply]), theory_end_ply=max(ply + 6, 12),
                                  objective_eval_cp=None, soundness="playable")
                    return GambitMatch(g, played_by_user=sign, window_end_ply=g.theory_end_ply,
                                       detected_by="material+eco")
    return None


def theory_moves_at(g: GambitDef, board: chess.Board) -> frozenset[str]:
    return g.theory_moves.get(fen_key(board), frozenset())


def judge_move(
    match: GambitMatch,
    board: chess.Board,
    move_uci: str,
    ply: int,
    depth: int | None = None,
    threshold_cp: int | None = None,
) -> GambitMoveVerdict:
    """Gambit-aware verdict for the *player's* move at ``ply`` (1-based).

    ``board`` is the position before the move.
    """
    threshold = threshold_cp or get_settings().mistake_threshold_cp
    g = match.gambit
    fen = board.fen()
    theory = theory_moves_at(g, board)

    # 1) Theory moves are never mistakes inside the window.
    if move_uci in theory:
        is_sac = ply <= len(g.trigger_uci) and move_uci == g.trigger_uci[ply - 1] and match.played_by_user
        return GambitMoveVerdict(tag="gambit_sacrifice" if is_sac else "gambit_theory")

    if not match.played_by_user:
        # Defender side: judge objectively; a big loss means the player fell for a trap.
        loss = engine.eval_loss(fen, move_uci, depth=depth)
        if loss > threshold:
            best = engine.evaluate(fen, depth=depth).best_move_uci
            return GambitMoveVerdict(tag="defender_trap", loss_cp=loss, reference_move=best,
                                     reason=f"lost {loss} cp against the {g.name}")
        return GambitMoveVerdict(tag="ok", loss_cp=loss)

    # 2) Player's own gambit: compare with the best gambit-keeping move.
    top = engine.evaluate(fen, depth=depth, multipv=5)
    keeping = set(theory) | {line.move_uci for line in top.lines}
    keeping.add(move_uci)
    scores = engine.evaluate_moves(fen, sorted(keeping), depth=depth)
    # Reference = best among theory moves when theory exists, else best engine move.
    ref_pool = {m: scores[m] for m in theory if m in scores} or {m: scores[m] for m in keeping if m != move_uci}
    if not ref_pool or move_uci not in scores:
        return GambitMoveVerdict(tag="ok")
    ref_move = max(ref_pool, key=ref_pool.get)
    loss = max(0, ref_pool[ref_move] - scores[move_uci])

    reasons = []
    if loss > threshold:
        reasons.append(f"lost {loss} cp versus the best gambit-keeping move")
    if g.objective_eval_cp is not None:
        baseline_player = g.objective_eval_cp if g.side == "white" else -g.objective_eval_cp
        if scores[move_uci] < baseline_player - BASELINE_TOLERANCE_CP:
            reasons.append(f"fell {baseline_player - scores[move_uci]} cp below the gambit baseline")
    if reasons:
        return GambitMoveVerdict(tag="gambit_deviation", loss_cp=loss, reference_move=ref_move,
                                 reason="; ".join(reasons))
    return GambitMoveVerdict(tag="ok", loss_cp=loss, reference_move=ref_move)


def informational_note(g: GambitDef, results: dict[str, int]) -> str | None:
    """One neutral note for a dubious gambit the player chose (never a push away)."""
    if g.soundness != "dubious":
        return None
    total = sum(results.values()) or 1
    score = (results.get("win", 0) + 0.5 * results.get("draw", 0)) / total
    ev = "not calibrated yet" if g.objective_eval_cp is None else f"{g.objective_eval_cp / 100:+.2f} (White's view)"
    return (f"You play the {g.name}. Engine evaluation at the end of main-line theory: {ev}. "
            f"Your practical score with it: {score:.0%} over {sum(results.values())} games. "
            "This is information only — keep playing it if it suits you.")


def all_gambit_names() -> list[str]:
    return sorted({g.name for g in registry().values() if g.is_real} | {n for _, n, _ in gambit_entries()})
