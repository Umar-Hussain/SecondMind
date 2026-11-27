"""Repertoire deviation analysis and ranking.

For every game where the player has the repertoire's color, the game is
replayed through the position-keyed tree:

1. user's turn, move in the repertoire (main or alternative) -> in book, continue;
2. user's turn, move not in the repertoire -> **user deviation**, stop;
3. opponent's turn, move not covered -> **uncovered line** (a gap in the
   repertoire, never the user's fault), stop;
4. a move that leaves the stored branch but lands on another position of the
   tree (a transposition) -> keep matching by position.

Deviations are grouped by ``(position, move played)``, judged with Stockfish
against the repertoire move and the engine best (player's point of view), and
ranked by number of games (most first), average loss as tie-break.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

import chess
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import RepertoireDeviation, UncoveredLine
from app.schemas import NormalizedGame, RepertoireDeviationOut, UncoveredLineOut
from app.tools import engine, gambits
from app.tools.pgn_utils import fen_key, uci_to_san
from app.tools.repertoire import RepTree

# (fen, color, gambit_id) -> (move_uci, source, reason) — the move recommender
AlternativePicker = Callable[[str, str, str | None, str | None], tuple[str | None, str | None, str]]


@dataclass
class MatchResult:
    kind: str  # in_book | user_deviation | uncovered
    ply: int = 0
    fen: str = ""  # full FEN of the position where it happened
    played: str | None = None
    repertoire_move: str | None = None
    transposed: bool = False
    moves_before: list[str] = field(default_factory=list)


def _has_content(tree: RepTree, key: str) -> bool:
    node = tree.nodes.get(key)
    return bool(node and (node.user_move or node.opponent_moves))


def match_game(game: NormalizedGame, tree: RepTree) -> MatchResult:
    """Replay ``game`` through ``tree`` and report where it leaves the repertoire."""
    board = chess.Board()
    user = tree.user_turn
    transposed = False
    for ply, uci in enumerate(game.moves_uci, start=1):
        key = fen_key(board)
        node = tree.nodes.get(key)
        move = chess.Move.from_uci(uci)
        after = board.copy()
        after.push(move)
        if node is None or not (node.user_move or node.opponent_moves):
            # End of a prepared branch — unless the next move transposes into another branch
            # (e.g. 2.Nc3 d5 3.d4 reaching the 2.d4 d5 3.Nc3 position).
            if _has_content(tree, fen_key(after)):
                transposed = True
                board = after
                continue
            return MatchResult("in_book", ply - 1, transposed=transposed)  # end of prepared lines
        if board.turn == user:
            if node.user_move is None:
                return MatchResult("in_book", ply - 1, transposed=transposed)
            if uci in node.user_moves():
                board = after
                continue
            if _has_content(tree, fen_key(after)):
                # The user reached another repertoire position by a different order.
                transposed = True
                board = after
                continue
            return MatchResult("user_deviation", ply, board.fen(), uci, node.user_move,
                               transposed, game.moves_uci[: ply - 1])
        if not node.opponent_moves:
            return MatchResult("in_book", ply - 1, transposed=transposed)
        if uci in node.opponent_moves:
            board = after
            continue
        if _has_content(tree, fen_key(after)):
            transposed = True
            board = after
            continue
        return MatchResult("uncovered", ply, board.fen(), uci, None, transposed, game.moves_uci[: ply - 1])
    return MatchResult("in_book", len(game.moves_uci), transposed=transposed)


@dataclass
class _Group:
    fen: str
    played: str
    repertoire_move: str | None
    games: list[NormalizedGame] = field(default_factory=list)
    gambit_ids: set[str] = field(default_factory=set)


def _judge(fen: str, played: str, rep_move: str, color: str, depth: int, gambit_id: str | None,
           intentional_gambit: bool) -> dict:
    """Classify one deviation with Stockfish."""
    s = get_settings()
    best = engine.evaluate(fen, depth=depth)
    scores = engine.evaluate_moves(fen, [played, rep_move], depth=depth)
    played_cp, rep_cp, best_cp = scores.get(played), scores.get(rep_move), best.cp_stm
    out = {"played_cp": played_cp, "repertoire_cp": rep_cp, "best_cp": best_cp, "best_move": best.best_move_uci}
    if played_cp is None or rep_cp is None:
        out.update(classification="unjudged", loss=0.0, reason="could not evaluate")
        return out

    loss_vs_rep = rep_cp - played_cp
    loss_vs_best = best_cp - played_cp
    rep_issue = best_cp - rep_cp > s.repertoire_issue_cp

    if gambit_id or intentional_gambit:
        # Gambit rule: judge against the best gambit-keeping move, never the global best.
        g = gambits.get(gambit_id) if gambit_id else None
        board = chess.Board(fen)
        ply = (board.fullmove_number - 1) * 2 + (1 if board.turn == chess.WHITE else 2)
        if g is not None:
            match = gambits.GambitMatch(g, played_by_user=(g.side == color), window_end_ply=g.theory_end_ply,
                                        detected_by="repertoire")
            verdict = gambits.judge_move(match, board, played, ply, depth=depth)
            mistake = verdict.tag in ("gambit_deviation", "defender_trap")
            out.update(classification="mistake" if mistake else ("better" if loss_vs_rep < -s.harmless_threshold_cp
                                                                  else "harmless"),
                       loss=float(max(0, loss_vs_rep)), repertoire_issue=False,
                       reason=verdict.reason or "keeps the gambit's compensation")
            return out
        loss_vs_best = loss_vs_rep  # intentional gambit without registry entry: compare with repertoire only
        rep_issue = False

    if max(loss_vs_rep, loss_vs_best) > s.mistake_threshold_cp:
        cls, reason = "mistake", f"loses {max(loss_vs_rep, loss_vs_best)} cp"
    elif loss_vs_rep < -s.harmless_threshold_cp:
        cls, reason = "better", f"better than the repertoire move by {-loss_vs_rep} cp: consider updating it"
    elif abs(loss_vs_rep) <= s.harmless_threshold_cp:
        cls, reason = "harmless", "within 30 cp of the repertoire move: could be added as an alternative"
    else:
        cls, reason = "inaccuracy", f"{loss_vs_rep} cp worse than the repertoire move"
    if rep_issue:
        reason += f"; note: the repertoire move itself is {best_cp - rep_cp} cp worse than the engine best"
    out.update(classification=cls, loss=float(max(0, loss_vs_rep)), repertoire_issue=rep_issue, reason=reason)
    return out


def _default_picker(fen: str, color: str, rep_move: str | None, gambit_id: str | None
                    ) -> tuple[str | None, str | None, str]:
    """Fallback when the full recommender is not wired: repertoire move if sound, else engine best."""
    best = engine.evaluate(fen)
    if rep_move:
        loss = engine.eval_loss(fen, rep_move)
        if loss <= get_settings().max_loss_cp:
            return rep_move, "repertoire", f"repertoire move, {loss} cp from the engine best"
    return best.best_move_uci, "engine", "engine best move"


def _status(game_ids: list[str], relevant_recent: list[str]) -> str:
    """open / improving / plugged from how often the deviation shows in recent games."""
    recent = relevant_recent[:10]
    hits_recent = sum(1 for g in recent if g in game_ids)
    if game_ids and hits_recent == 0 and len(recent) >= 5:
        return "plugged"
    older = len(game_ids) - hits_recent
    if hits_recent and older > hits_recent:
        return "improving"
    return "open"


def analyze_repertoire(
    games: Iterable[NormalizedGame],
    tree: RepTree,
    repertoire_id: int = 0,
    depth: int | None = None,
    intentional_gambit: bool = False,
    picker: AlternativePicker | None = None,
    judge: bool = True,
) -> tuple[list[RepertoireDeviationOut], list[UncoveredLineOut]]:
    """Match every game, group, judge, recommend and rank."""
    depth = depth or get_settings().engine_depth
    picker = picker or _default_picker
    relevant = [g for g in games if g.color == tree.color]
    relevant.sort(key=lambda g: g.played_at.timestamp() if g.played_at else 0, reverse=True)

    dev_groups: dict[tuple[str, str], _Group] = {}
    unc_groups: dict[tuple[str, str], _Group] = {}
    for g in relevant:
        m = match_game(g, tree)
        if m.kind == "in_book" or m.played is None:
            continue
        key = (fen_key(m.fen), m.played)
        target = dev_groups if m.kind == "user_deviation" else unc_groups
        grp = target.setdefault(key, _Group(m.fen, m.played, m.repertoire_move))
        grp.games.append(g)
        gm = gambits.detect_gambit(g.moves_uci, g.color)
        # Only a gambit deviation if it happens at/after the sacrifice and inside the theory window;
        # leaving the repertoire on move 3 in a game that later became an Evans Gambit is not one.
        if gm and gm.played_by_user and len(gm.gambit.trigger_uci) <= m.ply <= gm.window_end_ply:
            grp.gambit_ids.add(gm.gambit.id)

    recent_ids = [g.external_id for g in relevant]
    deviations: list[RepertoireDeviationOut] = []
    for (key, played), grp in dev_groups.items():
        results = {"win": 0, "draw": 0, "loss": 0}
        for g in grp.games:
            results[g.result] += 1
        gambit_id = next(iter(grp.gambit_ids), None)
        verdict = (_judge(grp.fen, played, grp.repertoire_move, tree.color, depth, gambit_id, intentional_gambit)
                   if judge and grp.repertoire_move else {"classification": "unjudged", "loss": 0.0, "reason": ""})
        rec, source, rec_reason = picker(grp.fen, tree.color, grp.repertoire_move, gambit_id) if judge else (None, None, "")
        ids = [g.external_id for g in grp.games]
        deviations.append(RepertoireDeviationOut(
            repertoire_id=repertoire_id, node_fen=grp.fen, color=tree.color,
            played_move=played, played_san=uci_to_san(grp.fen, played),
            repertoire_move=grp.repertoire_move,
            repertoire_san=uci_to_san(grp.fen, grp.repertoire_move) if grp.repertoire_move else "",
            recommended_move=rec, recommended_san=uci_to_san(grp.fen, rec) if rec else "",
            recommended_source=source,  # type: ignore[arg-type]
            reason="; ".join(x for x in (verdict.get("reason", ""), rec_reason) if x),
            classification=verdict["classification"], repertoire_issue=verdict.get("repertoire_issue", False),
            played_cp=verdict.get("played_cp"), repertoire_cp=verdict.get("repertoire_cp"),
            best_cp=verdict.get("best_cp"), is_gambit=bool(gambit_id or intentional_gambit),
            status=_status(ids, recent_ids), game_ids=ids,
            games_count=len(grp.games), results=results, avg_eval_loss=round(verdict.get("loss", 0.0), 1),
            game_links=[g.url for g in grp.games if g.url],
        ))
    deviations = rank_deviations(deviations)

    uncovered: list[UncoveredLineOut] = []
    for (key, opp_move), grp in unc_groups.items():
        after = chess.Board(grp.fen)
        after.push_uci(opp_move)
        reply = None
        if judge:
            reply, _, _ = picker(after.fen(), tree.color, None, None)
        uncovered.append(UncoveredLineOut(
            repertoire_id=repertoire_id, node_fen=grp.fen, opponent_move=opp_move,
            opponent_san=uci_to_san(grp.fen, opp_move), games_count=len(grp.games), suggested_reply=reply))
    uncovered.sort(key=lambda u: u.games_count, reverse=True)
    return deviations, uncovered


def rank_deviations(devs: list[RepertoireDeviationOut], sort: str = "games") -> list[RepertoireDeviationOut]:
    """``games``: most games first, avg loss as tie-break. ``impact``: games x avg loss."""
    if sort == "impact":
        return sorted(devs, key=lambda d: (d.games_count * d.avg_eval_loss, d.games_count), reverse=True)
    return sorted(devs, key=lambda d: (d.games_count, d.avg_eval_loss), reverse=True)


def store_results(session: Session, repertoire_id: int, deviations: list[RepertoireDeviationOut],
                  uncovered: list[UncoveredLineOut]) -> None:
    """Replace stored rows for this repertoire and write ids back into the outputs."""
    session.execute(delete(RepertoireDeviation).where(RepertoireDeviation.repertoire_id == repertoire_id))
    session.execute(delete(UncoveredLine).where(UncoveredLine.repertoire_id == repertoire_id))
    for d in deviations:
        row = RepertoireDeviation(
            repertoire_id=repertoire_id, node_fen_key=d.node_fen, played_move=d.played_move,
            repertoire_move=d.repertoire_move, recommended_move=d.recommended_move,
            recommended_source=d.recommended_source, classification=d.classification, reason=d.reason,
            games_count=d.games_count, results_json=d.results, avg_eval_loss=d.avg_eval_loss,
            game_ids_json={"ids": d.game_ids, "links": d.game_links, "repertoire_issue": d.repertoire_issue,
                           "played_cp": d.played_cp, "repertoire_cp": d.repertoire_cp, "best_cp": d.best_cp,
                           "is_gambit": d.is_gambit},
            status=d.status)
        session.add(row)
        session.flush()
        d.id = row.id
    for u in uncovered:
        row = UncoveredLine(repertoire_id=repertoire_id, node_fen_key=u.node_fen, opponent_move=u.opponent_move,
                            games_count=u.games_count, suggested_reply=u.suggested_reply)
        session.add(row)
        session.flush()
        u.id = row.id
    session.commit()


def load_deviations(session: Session, repertoire_id: int, color: str, sort: str = "games"
                    ) -> list[RepertoireDeviationOut]:
    rows = session.scalars(select(RepertoireDeviation).where(RepertoireDeviation.repertoire_id == repertoire_id))
    out = []
    for r in rows:
        extra = r.game_ids_json if isinstance(r.game_ids_json, dict) else {"ids": r.game_ids_json}
        out.append(RepertoireDeviationOut(
            id=r.id, repertoire_id=r.repertoire_id, node_fen=r.node_fen_key, color=color,  # type: ignore[arg-type]
            played_move=r.played_move, played_san=uci_to_san(r.node_fen_key, r.played_move),
            repertoire_move=r.repertoire_move,
            repertoire_san=uci_to_san(r.node_fen_key, r.repertoire_move) if r.repertoire_move else "",
            recommended_move=r.recommended_move,
            recommended_san=uci_to_san(r.node_fen_key, r.recommended_move) if r.recommended_move else "",
            recommended_source=r.recommended_source, reason=r.reason,  # type: ignore[arg-type]
            classification=r.classification, repertoire_issue=extra.get("repertoire_issue", False),  # type: ignore[arg-type]
            played_cp=extra.get("played_cp"), repertoire_cp=extra.get("repertoire_cp"),
            best_cp=extra.get("best_cp"), is_gambit=extra.get("is_gambit", False), status=r.status,
            game_ids=extra.get("ids", []), games_count=r.games_count, results=r.results_json,
            avg_eval_loss=r.avg_eval_loss, game_links=extra.get("links", [])))
    return rank_deviations(out, sort)
