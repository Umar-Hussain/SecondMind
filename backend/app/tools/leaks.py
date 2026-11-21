"""Leak mining (spec 5.2, 8.1, Phase 6).

A *leak* is a repeated ``(color, position, move)`` that costs the player
evaluation or results. Procedure per game:

1. Detect a gambit first. Moves inside the gambit window are judged only by
   the gambit rules (``gambits.judge_move``): theory moves are skipped, and
   only ``gambit_deviation`` / ``defender_trap`` findings are produced.
2. For every other player move in the opening phase (first 20 plies):
   * the **first** move that is not master theory is a *deviation*;
   * any move losing more than the threshold (80 cp) versus the engine best
     is a *mistake*.
3. Aggregate by ``(color, fen_key, played_move)`` and rank by
   ``frequency x average loss``.
4. A deviation alone is not a leak: it is kept only when the engine confirms a
   real loss or the player repeats it with poor results (spec 8.1 step 5).

All evaluations are from the player's point of view.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

import chess
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Leak, Quiz
from app.schemas import NormalizedGame
from app.tools import engine, gambits, masters
from app.tools.openings import classify
from app.tools.pgn_utils import fen_key

POOR_SCORE = 0.35  # "poor results" for a repeated non-losing deviation

# (fen, color, gambit_id or None) -> recommended move UCI
Recommender = Callable[[str, str, str | None], str | None]


@dataclass
class Finding:
    """One flagged move in one game."""

    game_id: str
    ply: int
    color: str
    fen: str
    played: str
    kind: str  # mistake | deviation | gambit_deviation | defender_trap
    loss_cp: int
    result: str
    reference_move: str | None = None
    gambit_id: str | None = None
    reason: str = ""
    opening_eco: str = ""
    opening_name: str = ""


@dataclass
class LeakOut:
    color: str
    fen: str
    played: str
    kind: str
    ply: int
    frequency: int
    games: list[str]
    results: dict[str, int]
    avg_loss: float
    theory_move: str | None
    opening_eco: str
    opening_name: str
    gambit_id: str | None = None
    note: str = ""
    examples: list[Finding] = field(default_factory=list)

    @property
    def score(self) -> float:
        """Ranking score: frequency x average loss (min 1 so repeats still rank)."""
        return self.frequency * max(self.avg_loss, 1.0)

    @property
    def player_score(self) -> float:
        total = sum(self.results.values()) or 1
        return (self.results.get("win", 0) + 0.5 * self.results.get("draw", 0)) / total


def analyze_game(game: NormalizedGame, depth: int | None = None, threshold: int | None = None) -> list[Finding]:
    """Flag the player's opening moves in one game."""
    s = get_settings()
    threshold = threshold or s.mistake_threshold_cp
    depth = depth or s.engine_depth
    player = chess.WHITE if game.color == "white" else chess.BLACK
    opening = classify(game.moves_uci)
    match = gambits.detect_gambit(game.moves_uci, game.color)

    board = chess.Board()
    findings: list[Finding] = []
    left_theory = False
    for ply, uci in enumerate(game.moves_uci[: s.opening_plies], start=1):
        move = chess.Move.from_uci(uci)
        if board.turn != player:
            board.push(move)
            continue

        fen = board.fen()
        base = dict(game_id=game.external_id, ply=ply, color=game.color, fen=fen, played=uci,
                    result=game.result, opening_eco=opening.eco, opening_name=opening.name)

        # --- Gambit window: gambit rules only --------------------------------
        # A main-line gambit move is never a mistake, even a ply or two past theory_end_ply
        # (found by the evaluation: 3 false positives on Danish / Morra / Englund main lines).
        if match and uci in gambits.theory_moves_at(match.gambit, board):
            board.push(move)
            continue
        if match and ply <= match.window_end_ply:
            verdict = gambits.judge_move(match, board, uci, ply, depth=depth, threshold_cp=threshold)
            if verdict.tag in ("gambit_deviation", "defender_trap"):
                findings.append(Finding(**base, kind=verdict.tag, loss_cp=verdict.loss_cp,
                                        reference_move=verdict.reference_move, gambit_id=match.gambit.id,
                                        reason=verdict.reason))
                # The gambit is over once it has been damaged; later moves are judged
                # by the ordinary rules instead of being flagged again against the baseline.
                match = None
                left_theory = True
            board.push(move)
            continue

        # --- Ordinary rules ---------------------------------------------------
        theory = masters.is_theory(fen, uci)
        if theory:
            # Master theory moves are trusted; no engine call needed.
            board.push(move)
            continue
        loss = engine.eval_loss(fen, uci, depth=depth)
        best = engine.evaluate(fen, depth=depth).best_move_uci
        if loss > threshold:
            findings.append(Finding(**base, kind="mistake", loss_cp=loss, reference_move=best,
                                    reason=f"lost {loss} cp versus the engine best"))
        elif not left_theory:
            findings.append(Finding(**base, kind="deviation", loss_cp=loss, reference_move=best,
                                    reason="first move outside master theory"))
        left_theory = True
        board.push(move)
    return findings


def aggregate(findings: Iterable[Finding], threshold: int | None = None) -> list[LeakOut]:
    """Group findings by (color, position, move) and apply the leak rules."""
    threshold = threshold or get_settings().mistake_threshold_cp
    groups: dict[tuple[str, str, str], list[Finding]] = defaultdict(list)
    for f in findings:
        groups[(f.color, fen_key(f.fen), f.played)].append(f)

    leaks: list[LeakOut] = []
    for (color, key, played), items in groups.items():
        games = sorted({f.game_id for f in items})
        results: dict[str, int] = defaultdict(int)
        for gid in games:
            results[next(f.result for f in items if f.game_id == gid)] += 1
        avg = sum(f.loss_cp for f in items) / len(items)
        # Most severe kind present wins.
        kinds = {f.kind for f in items}
        kind = next(k for k in ("defender_trap", "gambit_deviation", "mistake", "deviation") if k in kinds)
        first = items[0]
        leak = LeakOut(color=color, fen=first.fen, played=played, kind=kind, ply=first.ply,
                       frequency=len(items), games=games, results=dict(results), avg_loss=round(avg, 1),
                       theory_move=first.reference_move, opening_eco=first.opening_eco,
                       opening_name=first.opening_name, gambit_id=first.gambit_id, examples=items[:3])
        if kind == "deviation":
            # Deviation alone is not a leak: needs real loss or repeated poor results.
            repeated_poor = leak.frequency >= 2 and leak.player_score <= POOR_SCORE
            if not (avg > threshold or repeated_poor):
                continue
        leaks.append(leak)
    leaks.sort(key=lambda lk: lk.score, reverse=True)
    return leaks


def gambit_notes(games: Iterable[NormalizedGame]) -> list[LeakOut]:
    """One informational item per dubious gambit the player chooses (never a mistake)."""
    per: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    sample: dict[str, NormalizedGame] = {}
    for g in games:
        m = gambits.detect_gambit(g.moves_uci, g.color)
        if m and m.played_by_user and m.gambit.soundness == "dubious":
            per[m.gambit.id][g.result] += 1
            sample.setdefault(m.gambit.id, g)
    notes = []
    for gid, results in per.items():
        gdef = gambits.get(gid)
        if gdef is None:
            continue
        g = sample[gid]
        # Position *before* the defining gambit move, so (fen, played) is a legal pair.
        board = chess.Board()
        for u in gdef.trigger_uci[:-1]:
            board.push_uci(u)
        notes.append(LeakOut(color=g.color, fen=board.fen(), played=gdef.trigger_uci[-1], kind="gambit_note",
                             ply=len(gdef.trigger_uci), frequency=sum(results.values()), games=[],
                             results=dict(results), avg_loss=0.0, theory_move=None, opening_eco=gdef.eco or "",
                             opening_name=gdef.name, gambit_id=gid,
                             note=gambits.informational_note(gdef, dict(results)) or ""))
    return notes


def mine_leaks(
    games: Iterable[NormalizedGame],
    depth: int | None = None,
    threshold: int | None = None,
    recommender: Recommender | None = None,
) -> list[LeakOut]:
    """Full pipeline: analyse every game, aggregate, attach the recommended move."""
    games = list(games)
    findings: list[Finding] = []
    for g in games:
        findings.extend(analyze_game(g, depth=depth, threshold=threshold))
    leaks = aggregate(findings, threshold=threshold)
    if recommender:
        for lk in leaks:
            rec = recommender(lk.fen, lk.color, lk.gambit_id)
            if rec:
                lk.theory_move = rec
    return leaks + gambit_notes(games)


def store_leaks(session: Session, user_id: int, leaks: Iterable[LeakOut], game_db_ids: dict[str, int] | None = None,
                top: int = 30) -> list[Leak]:
    """Replace the user's open leaks with the freshly mined top leaks."""
    old = select(Leak.id).where(Leak.user_id == user_id, Leak.status == "open")
    # Quizzes made from old leaks stay (they are keyed by position); only the link is cleared,
    # otherwise databases that enforce foreign keys would refuse to delete the old leaks.
    session.execute(update(Quiz).where(Quiz.leak_id.in_(old)).values(leak_id=None))
    session.execute(delete(Leak).where(Leak.user_id == user_id, Leak.status == "open"))
    rows = []
    for lk in list(leaks)[:top]:
        row = Leak(user_id=user_id, opening_eco=lk.opening_eco, opening_name=lk.opening_name, color=lk.color,
                   ply=lk.ply, fen_before=lk.fen, played_move=lk.played, theory_move=lk.theory_move,
                   eval_loss_cp=lk.avg_loss, frequency=lk.frequency, games_count=len(lk.games) or lk.frequency,
                   status="open", kind=lk.kind, gambit_id=lk.gambit_id,
                   game_ids_json=[(game_db_ids or {}).get(g, g) for g in lk.games])
        session.add(row)
        rows.append(row)
    session.commit()
    return rows
