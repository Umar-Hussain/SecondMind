"""Practical move recommender: masters versus Stockfish (spec 5.4, 8.2, Phase 11).

Rule (thresholds in config):

1. Get master moves with counts. If the position has fewer than
   ``MIN_MASTER_GAMES`` master games, go straight to step 5.
2. Get Stockfish's top lines; ``best_cp`` is the best evaluation for the side to move.
3. Walk master moves from most to least popular. A move is **acceptable** when
   * ``best_cp - move_cp <= MAX_LOSS_CP``,
   * it does not turn a better position into an equal/worse one
     (``best_cp >= +100`` needs ``move_cp >= +60``; ``best_cp >= +30`` needs ``move_cp >= 0``),
   * it does not leave the player below ``-50`` in an otherwise balanced position.
4. The most popular acceptable move wins -> ``source = "master"``.
5. Otherwise Stockfish's best move -> ``source = "engine"``.
6. The reason (popularity, loss, failed condition of rejected moves) is stored.
7. The final move passes ``verify_recommendation``.
8. **Gambit mode**: inside a gambit the reference is the best *gambit-keeping*
   move (restricted analysis over the gambit's theory moves), candidates are
   gambit theory moves, and a non-gambit engine move never replaces a gambit
   move unless the gambit move is a real mistake by that measure.
"""

from __future__ import annotations

from collections.abc import Callable

import chess
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import MoveRecommendation
from app.schemas import MasterStats, MoveRecommendationOut
from app.tools import engine, gambits, masters
from app.tools.verify import verify_recommendation

MasterProvider = Callable[[str], MasterStats]
MAX_MASTER_CANDIDATES = 8


def _check(best_cp: int, move_cp: int, max_loss: int) -> str | None:
    """Return the failed condition, or None when the move is acceptable."""
    loss = best_cp - move_cp
    if loss > max_loss:
        return f"lost {loss} cp"
    if best_cp >= 100 and move_cp < 60:
        return "gave away the advantage"
    if best_cp >= 30 and move_cp < 0:
        return "gave away the edge"
    if -50 < best_cp < 30 and move_cp < -50:
        return "left you worse in a balanced position"
    return None


def engine_candidates(fen: str, multipv: int | None = None, depth: int | None = None):
    s = get_settings()
    return engine.evaluate(fen, depth=depth or s.engine_depth, multipv=multipv or s.recommender_multipv)


def recommend_move(
    fen: str,
    side: str | None = None,
    gambit_id: str | None = None,
    depth: int | None = None,
    master_provider: MasterProvider | None = None,
    objective: bool = False,
) -> MoveRecommendationOut:
    """Recommend a move for the side to move in ``fen`` (see module docstring)."""
    s = get_settings()
    board = chess.Board(fen)
    side = side or ("white" if board.turn == chess.WHITE else "black")
    stats = (master_provider or masters.master_moves)(fen)
    top = engine_candidates(fen, depth=depth)

    # --- Gambit mode -----------------------------------------------------------
    gdef = gambits.get(gambit_id) if (gambit_id and not objective) else None
    theory = sorted(gambits.theory_moves_at(gdef, board)) if gdef else []
    gambit_mode = bool(theory)

    master_list = [m for m in stats.moves if chess.Move.from_uci(m.uci) in board.legal_moves][:MAX_MASTER_CANDIDATES]
    if gambit_mode:
        # Candidates are gambit theory moves only, ordered by master popularity when known.
        pop = {m.uci: m.games for m in master_list}
        candidates = sorted(theory, key=lambda u: pop.get(u, 0), reverse=True)
        scores = engine.evaluate_moves(fen, candidates, depth=depth)
        best_uci = max(scores, key=scores.get)
        best_cp = scores[best_uci]
    else:
        candidates = [m.uci for m in master_list]
        scores = engine.evaluate_moves(fen, candidates, depth=depth) if candidates else {}
        best_uci, best_cp = top.best_move_uci, top.cp_stm

    rejected: list[dict] = []
    chosen: str | None = None
    source = "engine"
    reason = ""
    enough_masters = stats.total_games >= s.min_master_games

    if gambit_mode or enough_masters:
        for uci in candidates:
            cp = scores.get(uci)
            if cp is None:
                continue
            failed = _check(best_cp, cp, s.max_loss_cp)
            if gdef and gdef.objective_eval_cp is not None and failed is None:
                base = gdef.objective_eval_cp if side == "white" else -gdef.objective_eval_cp
                if cp < base - gambits.BASELINE_TOLERANCE_CP:
                    failed = f"fell {base - cp} cp below the {gdef.name} baseline"
            san = board.san(chess.Move.from_uci(uci))
            if failed:
                rejected.append({"move": uci, "san": san, "cp": cp, "failed": failed})
                continue
            chosen = uci
            source = "master"
            games = next((m.games for m in master_list if m.uci == uci), 0)
            share = games / stats.total_games if stats.total_games else 0
            pop_txt = (f"played in {share:.0%} of {stats.total_games} master games ({stats.source})"
                       if games else f"main-line {gdef.name if gdef else ''} theory")
            reason = f"{san}: {pop_txt}, {best_cp - cp} cp from the best" + (
                " gambit-keeping move" if gambit_mode else " engine move")
            break

    if chosen is None:
        chosen = best_uci
        source = "engine"
        san = board.san(chess.Move.from_uci(chosen))
        if not enough_masters and not gambit_mode:
            reason = f"{san}: Stockfish best; fewer than {s.min_master_games} master games in this position"
        else:
            reason = f"{san}: Stockfish best; no popular master move was acceptable"

    if rejected:
        reason += ". Rejected: " + ", ".join(f"{r['san']} ({r['failed']})" for r in rejected[:3])

    chosen_cp = scores.get(chosen, best_cp if chosen == best_uci else None)
    ver = verify_recommendation(fen, chosen, max_loss_cp=max(s.max_loss_cp, 40), depth=depth,
                                reference_moves=theory if gambit_mode else None)
    return MoveRecommendationOut(
        fen=fen, side=side, chosen_uci=chosen, chosen_san=board.san(chess.Move.from_uci(chosen)),
        chosen_source=source, chosen_cp=chosen_cp, engine_best_uci=top.best_move_uci, engine_best_cp=top.cp_stm,
        reason=reason, rejected=rejected, master_moves=master_list,
        gambit_id=gdef.id if gambit_mode and gdef else None, verified=ver.ok,
    )


def save(session: Session, rec: MoveRecommendationOut) -> MoveRecommendation:
    row = MoveRecommendation(fen=rec.fen, side=rec.side, master_moves_json=[m.model_dump() for m in rec.master_moves],
                             engine_best_uci=rec.engine_best_uci, engine_best_cp=rec.engine_best_cp,
                             chosen_uci=rec.chosen_uci, chosen_source=rec.chosen_source, chosen_cp=rec.chosen_cp,
                             reason=rec.reason, gambit_id=rec.gambit_id)
    session.add(row)
    session.commit()
    return row


# ---------------------------------------------------------------------------
# Adapters used by leak mining and deviation analysis
# ---------------------------------------------------------------------------


def leak_recommender(depth: int | None = None):
    """(fen, color, gambit_id) -> recommended move, for ``leaks.mine_leaks``."""
    def _rec(fen: str, color: str, gambit_id: str | None) -> str | None:
        return recommend_move(fen, color, gambit_id=gambit_id, depth=depth).chosen_uci
    return _rec


def repertoire_picker(depth: int | None = None):
    """Deviation picker: the repertoire move if sound, else the recommender (spec 8.8)."""
    s = get_settings()

    def _pick(fen: str, color: str, rep_move: str | None, gambit_id: str | None):
        if rep_move:
            board = chess.Board(fen)
            best = engine.evaluate(fen, depth=depth)
            if gambit_id and gambits.get(gambit_id):
                theory = sorted(gambits.theory_moves_at(gambits.get(gambit_id), board))
                if rep_move in theory:
                    return rep_move, "repertoire", "repertoire move (gambit theory)"
            rep_cp = engine.evaluate_moves(fen, [rep_move], depth=depth).get(rep_move)
            if rep_cp is not None and _check(best.cp_stm, rep_cp, s.max_loss_cp) is None:
                return rep_move, "repertoire", f"your repertoire move is sound ({best.cp_stm - rep_cp} cp from best)"
        rec = recommend_move(fen, color, gambit_id=gambit_id, depth=depth)
        return rec.chosen_uci, rec.chosen_source, rec.reason

    return _pick
