"""Extra preparation lines and novelties against one opponent (spec 5.8, 5.9, 8.4).

Extra lines are *outside* the player's repertoire, follow popular master moves
while they are sound (every player move comes from the recommender), are at
most ``MAX_PLIES`` plies of preparation, and must end at least equal for the
player (``eval >= 0``). Opponent moves are taken from the opponent's own most
repeated line, so the line is something they actually play.
"""

from __future__ import annotations

import chess

from app.schemas import ExtraLine
from app.tools import engine, masters, rag
from app.tools.pgn_utils import line_to_san
from app.tools.recommend import recommend_move

MAX_PLIES = 16  # 8 moves of preparation per side at most
NOVELTY_WINDOW_CP = 30


def extra_line(opponent_line: list[str], player_color: str, depth: int | None = None,
               start_ply: int = 0, max_plies: int = MAX_PLIES) -> ExtraLine | None:
    """Follow the opponent's repeated line, choose the player's moves with the recommender."""
    me = chess.WHITE if player_color == "white" else chess.BLACK
    board = chess.Board()
    for u in opponent_line[:start_ply]:
        board.push_uci(u)
    start_fen = board.fen()
    moves: list[str] = []
    for ply in range(start_ply, min(len(opponent_line), start_ply + max_plies)):
        if board.is_game_over():
            break
        if board.turn == me:
            u = recommend_move(board.fen(), player_color, depth=depth).chosen_uci
        else:
            u = opponent_line[ply]
            if chess.Move.from_uci(u) not in board.legal_moves:
                break  # the player's prep left the opponent's habitual line
        moves.append(u)
        board.push_uci(u)
        # Stop once the opponent leaves their habit (our move differs from what they faced).
        if board.turn != me and ply + 1 < len(opponent_line) and opponent_line[ply] != u:
            break
    if not moves:
        return None
    final = engine.evaluate(board.fen(), depth=depth)
    final_cp_player = final.cp_white if me == chess.WHITE else -final.cp_white
    if final_cp_player < 0:
        return None  # reject lines that leave the player worse
    n_player_moves = sum(1 for i in range(len(moves)) if (i % 2 == 0) == (chess.Board(start_fen).turn == me))
    return ExtraLine(moves=moves, moves_san=line_to_san(start_fen, moves), start_fen=start_fen,
                     goal="", final_eval_cp=final_cp_player, study_minutes=max(5, 2 * n_player_moves),
                     in_repertoire=False)


def find_novelty(fen: str, depth: int | None = None) -> dict | None:
    """A move within 30 cp of the best that masters rarely or never play here."""
    top = engine.evaluate(fen, depth=depth, multipv=5)
    stats = masters.master_moves(fen)
    popular = {m.uci for m in stats.moves if stats.total_games and m.games / stats.total_games >= 0.05}
    board = chess.Board(fen)
    for line in top.lines[1:]:
        if top.cp_stm - line.cp <= NOVELTY_WINDOW_CP and line.move_uci not in popular:
            return {"fen": fen, "move": line.move_uci, "san": board.san(chess.Move.from_uci(line.move_uci)),
                    "loss_cp": top.cp_stm - line.cp, "master_share": 0.0, "pv_san": line.pv_san[:6]}
    return None


def cite_for(opening: str, eco: str | None) -> list:
    return rag.master_games_for(eco, opening, k=1)


def study_budget_ok(lines: list[ExtraLine], minutes: int) -> bool:
    return sum(x.study_minutes for x in lines) <= minutes

