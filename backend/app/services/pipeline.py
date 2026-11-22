"""End-to-end analysis pipeline used by the API, the agent and scheduled jobs.

``run_analysis`` = fetch games (both platforms) -> store -> mine leaks with the
recommender -> store leaks -> analyse every active repertoire. Deterministic:
the LLM is only used later, when the report explains the stored facts.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import chess

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Game, Leak, Repertoire, RepertoireDeviation, UncoveredLine, User
from app.schemas import NormalizedGame
from app.tools import deviations, leaks
from app.tools.openings import classify
from app.tools.pgn_utils import fen_key, uci_to_san
from app.tools.games import fetch_user_games, store_games, to_normalized
from app.tools.recommend import leak_recommender, repertoire_picker
from app.tools.repertoire import load_tree


Progress = Callable[[str, int, int], None]


@dataclass
class AnalysisSummary:
    user_id: int
    games_fetched: int = 0
    games_new: int = 0
    leaks: int = 0
    repertoires_analyzed: int = 0
    deviations: int = 0
    uncovered: int = 0
    warnings: list[str] = field(default_factory=list)


def user_games(session: Session, user_id: int) -> list[NormalizedGame]:
    rows = session.scalars(select(Game).where(Game.user_id == user_id).order_by(Game.played_at.desc()))
    return [to_normalized(g) for g in rows]


def leak_from_row(row: Leak) -> leaks.LeakOut:
    """Rebuild a LeakOut from a stored row (for reports built later)."""
    return leaks.LeakOut(color=row.color, fen=row.fen_before, played=row.played_move, kind=row.kind, ply=row.ply,
                         frequency=row.frequency, games=[str(g) for g in row.game_ids_json or []],
                         results={}, avg_loss=row.eval_loss_cp, theory_move=row.theory_move,
                         opening_eco=row.opening_eco or "", opening_name=row.opening_name or "",
                         gambit_id=row.gambit_id)


def analyze_repertoires(session: Session, user_id: int, games: list[NormalizedGame], depth: int | None = None,
                        progress: Progress | None = None) -> tuple[int, int, int]:
    reps = list(session.scalars(select(Repertoire).where(Repertoire.user_id == user_id, Repertoire.status == "active")))
    n_rep = n_dev = n_unc = 0
    for i, rep in enumerate(reps, start=1):
        if progress:
            progress("repertoires", i, len(reps))
        tree = load_tree(session, rep.id)
        devs, unc = deviations.analyze_repertoire(games, tree, rep.id, depth=depth,
                                                  intentional_gambit=rep.intentional_gambit,
                                                  picker=repertoire_picker(depth))
        deviations.store_results(session, rep.id, devs, unc)
        n_rep, n_dev, n_unc = n_rep + 1, n_dev + len(devs), n_unc + len(unc)
    return n_rep, n_dev, n_unc


def run_analysis(session: Session, user_id: int, max_games: int = 200, depth: int | None = None,
                 fetch: bool = True, progress: Progress | None = None) -> AnalysisSummary:
    """Fetch, store, mine leaks, analyse repertoires. ``progress(stage, done, total)`` reports
    each step (stages: download, games, moves, repertoires) for the background job."""
    user = session.get(User, user_id)
    if user is None:
        raise KeyError(f"user {user_id} not found")
    summary = AnalysisSummary(user_id=user_id)
    if fetch:
        if progress:
            progress("download", 0, 1)
        fetched, warnings = fetch_user_games(user, max_games=max_games)
        summary.games_fetched, summary.warnings = len(fetched), warnings
        summary.games_new = store_games(session, user_id, fetched)
    games = user_games(session, user_id)[:max_games]
    mined = leaks.mine_leaks(games, depth=depth, recommender=leak_recommender(depth), progress=progress)
    leaks.store_leaks(session, user_id, mined)
    summary.leaks = len(mined)
    summary.repertoires_analyzed, summary.deviations, summary.uncovered = analyze_repertoires(
        session, user_id, games, depth, progress)
    return summary


def stored_leaks(session: Session, user_id: int) -> list[leaks.LeakOut]:
    rows = session.scalars(select(Leak).where(Leak.user_id == user_id).order_by(Leak.id))
    out = [leak_from_row(r) for r in rows]
    return sorted(out, key=lambda lk: (lk.kind == "gambit_note", -lk.score))


# --- Opening overview (Deviations page, step 2) ----------------------------------------

def _san_line(moves: list[str]) -> str:
    """UCI moves from the start position -> "1.e4 c6 2.d4" (stops at the first bad move)."""
    board, out = chess.Board(), []
    for i, uci in enumerate(moves):
        try:
            move = chess.Move.from_uci(uci)
            san = board.san(move)
        except ValueError:
            break
        out.append(f"{i // 2 + 1}.{san}" if i % 2 == 0 else san)
        board.push(move)
    return " ".join(out)


def _link_stored(session: Session, exit_: dict) -> None:
    """Attach what the last analysis stored for this exit point: the deviation row (for the
    explanation and the recommended move) or the uncovered line (for the suggested reply).
    Stored rows keep the full FEN, so positions are compared on their first four fields."""
    key = fen_key(chess.Board(exit_["fen"]))
    exit_["deviation_id"] = exit_["suggested_reply"] = exit_["suggested_san"] = exit_["recommended_move"] = None
    if exit_["state"] == "you_left":
        row = next((r for r in session.scalars(select(RepertoireDeviation).where(
            RepertoireDeviation.repertoire_id == exit_["repertoire_id"],
            RepertoireDeviation.played_move == exit_["played"])) if fen_key(r.node_fen_key) == key), None)
        if row is not None:
            exit_["deviation_id"], exit_["recommended_move"] = row.id, row.recommended_move
    else:
        row = next((r for r in session.scalars(select(UncoveredLine).where(
            UncoveredLine.repertoire_id == exit_["repertoire_id"],
            UncoveredLine.opponent_move == exit_["played"])) if fen_key(r.node_fen_key) == key), None)
        if row is not None and row.suggested_reply:
            after = chess.Board(exit_["fen"])
            after.push_uci(exit_["played"])
            exit_["suggested_reply"], exit_["suggested_san"] = row.suggested_reply, uci_to_san(after.fen(), row.suggested_reply)
    exit_["fen_key"] = key


def opening_overview(session: Session, user_id: int, limit: int = 300) -> dict:
    """Group the user's stored games by opening and check each group against their repertoires.

    For every game the repertoire of the same colour that follows it furthest is chosen
    (``deviations.match_game``). A game then ends up in one of four states:

    * ``in_book``   - the game stayed inside the repertoire until the prepared lines ran out;
    * ``you_left``  - the user played a move that is not in their repertoire;
    * ``opponent``  - the opponent played a move the repertoire does not cover yet;
    * ``none``      - no repertoire covers this opening (fewer than two moves matched).

    Each opening group keeps its most common exit point, so the page can show the
    position on a board with the move played and the move the repertoire wanted.
    """
    games = user_games(session, user_id)[:limit]
    reps = list(session.scalars(select(Repertoire).where(Repertoire.user_id == user_id,
                                                         Repertoire.status == "active")))
    trees = {r.id: load_tree(session, r.id) for r in reps}
    groups: dict[tuple[str, str], dict] = {}
    for g in games:
        info = classify(g.moves_uci[:24]) if g.moves_uci else None
        # Group by opening family ("Italian Game: Two Knights Defense" -> "Italian Game") so
        # small move-order differences do not split one opening into many rows.
        name = (info.name if info else "Unknown Opening").split(":")[0].strip()
        best, best_rep = None, None
        for rep in reps:
            if rep.color != g.color:
                continue
            m = deviations.match_game(g, trees[rep.id])
            if best is None or m.ply > best.ply:
                best, best_rep = m, rep
        if best is None or best.ply < 2:
            state = "none"
        else:
            state = {"in_book": "in_book", "user_deviation": "you_left", "uncovered": "opponent"}[best.kind]
        grp = groups.setdefault((g.color, name), {
            "color": g.color, "opening": name, "eco": info.eco if info else "", "games": 0,
            "results": {"win": 0, "draw": 0, "loss": 0}, "states": {"in_book": 0, "you_left": 0, "opponent": 0, "none": 0},
            "repertoire_id": None, "repertoire_name": None, "_exits": {}, "sample_line": _san_line(g.moves_uci[:8]),
        })
        grp["games"] += 1
        grp["results"][g.result] = grp["results"].get(g.result, 0) + 1
        grp["states"][state] += 1
        if best_rep is not None and state != "none":
            grp["repertoire_id"], grp["repertoire_name"] = best_rep.id, best_rep.name
        if state in ("you_left", "opponent"):
            key = (state, best.fen, best.played)
            ex = grp["_exits"].setdefault(key, {"state": state, "fen": best.fen, "played": best.played,
                                                 "repertoire_move": best.repertoire_move, "games": 0,
                                                 "line": _san_line(best.moves_before), "repertoire_id": best_rep.id})
            ex["games"] += 1
    out = []
    for grp in groups.values():
        exits = sorted(grp.pop("_exits").values(), key=lambda e: -e["games"])
        for e in exits:
            e["played_san"] = uci_to_san(e["fen"], e["played"])
            e["repertoire_san"] = uci_to_san(e["fen"], e["repertoire_move"]) if e["repertoire_move"] else None
            _link_stored(session, e)
        grp["exits"] = exits[:3]
        out.append(grp)
    out.sort(key=lambda x: -x["games"])
    return {"games": len(games), "repertoires": len(reps), "openings": out}
