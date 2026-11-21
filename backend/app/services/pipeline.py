"""End-to-end analysis pipeline used by the API, the agent and scheduled jobs.

``run_analysis`` = fetch games (both platforms) -> store -> mine leaks with the
recommender -> store leaks -> analyse every active repertoire. Deterministic:
the LLM is only used later, when the report explains the stored facts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Game, Leak, Repertoire, User
from app.schemas import NormalizedGame
from app.tools import deviations, leaks
from app.tools.games import fetch_user_games, store_games, to_normalized
from app.tools.recommend import leak_recommender, repertoire_picker
from app.tools.repertoire import load_tree


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


def analyze_repertoires(session: Session, user_id: int, games: list[NormalizedGame], depth: int | None = None
                        ) -> tuple[int, int, int]:
    reps = session.scalars(select(Repertoire).where(Repertoire.user_id == user_id, Repertoire.status == "active"))
    n_rep = n_dev = n_unc = 0
    for rep in reps:
        tree = load_tree(session, rep.id)
        devs, unc = deviations.analyze_repertoire(games, tree, rep.id, depth=depth,
                                                  intentional_gambit=rep.intentional_gambit,
                                                  picker=repertoire_picker(depth))
        deviations.store_results(session, rep.id, devs, unc)
        n_rep, n_dev, n_unc = n_rep + 1, n_dev + len(devs), n_unc + len(unc)
    return n_rep, n_dev, n_unc


def run_analysis(session: Session, user_id: int, max_games: int = 200, depth: int | None = None,
                 fetch: bool = True) -> AnalysisSummary:
    user = session.get(User, user_id)
    if user is None:
        raise KeyError(f"user {user_id} not found")
    summary = AnalysisSummary(user_id=user_id)
    if fetch:
        fetched, warnings = fetch_user_games(user, max_games=max_games)
        summary.games_fetched, summary.warnings = len(fetched), warnings
        summary.games_new = store_games(session, user_id, fetched)
    games = user_games(session, user_id)[:max_games]
    mined = leaks.mine_leaks(games, depth=depth, recommender=leak_recommender(depth))
    leaks.store_leaks(session, user_id, mined)
    summary.leaks = len(mined)
    summary.repertoires_analyzed, summary.deviations, summary.uncovered = analyze_repertoires(
        session, user_id, games, depth)
    return summary


def stored_leaks(session: Session, user_id: int) -> list[leaks.LeakOut]:
    rows = session.scalars(select(Leak).where(Leak.user_id == user_id).order_by(Leak.id))
    out = [leak_from_row(r) for r in rows]
    return sorted(out, key=lambda lk: (lk.kind == "gambit_note", -lk.score))
