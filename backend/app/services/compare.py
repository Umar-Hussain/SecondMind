"""Side-by-side comparison for one deviation (Deviations page, split screen).

For the position where the user left their repertoire it returns three lines, each
starting from that position:

* ``you``        - the move the user played and how their games usually went on
                   (majority move at every ply among their games that reached it);
* ``repertoire`` - the repertoire move and the prepared line after it (main moves);
* ``suggestion`` - Stockfish's best move and its principal variation.

Every move the user makes in these lines gets a quality symbol from ``annotate``.
"""

from __future__ import annotations

from collections import Counter

import chess

from app.services.pipeline import user_games
from app.tools import engine
from app.tools.annotate import annotate
from app.tools.pgn_utils import fen_key
from app.tools.repertoire import RepTree, load_tree

LINE_PLIES = 8


def _san_moves(fen: str, ucis: list[str]) -> list[dict]:
    board, out = chess.Board(fen), []
    for u in ucis:
        move = chess.Move.from_uci(u)
        if move not in board.legal_moves:
            break
        out.append({"uci": u, "san": board.san(move), "fen_before": board.fen()})
        board.push(move)
    return out


def games_continuation(games, key: str, played: str, plies: int = LINE_PLIES) -> tuple[list[str], int]:
    """Majority continuation after ``played`` from position ``key`` in the user's games."""
    seqs: list[list[str]] = []
    for g in games:
        board = chess.Board()
        for i, uci in enumerate(g.moves_uci):
            if fen_key(board) == key:
                if uci == played:
                    seqs.append(g.moves_uci[i + 1: i + 1 + plies])
                break
            try:
                board.push_uci(uci)
            except ValueError:
                break
            if i > 40:
                break
    line: list[str] = []
    pool = seqs
    for k in range(plies):
        nxt = Counter(s[k] for s in pool if len(s) > k)
        if not nxt:
            break
        move, _ = nxt.most_common(1)[0]
        line.append(move)
        pool = [s for s in pool if len(s) > k and s[k] == move]
    return line, len(seqs)


def tree_line(tree: RepTree, board: chess.Board, plies: int = LINE_PLIES) -> list[str]:
    """Main line of the repertoire from ``board``: your main move, the first stored reply."""
    b, out = board.copy(), []
    user = chess.WHITE if tree.color == "white" else chess.BLACK
    for _ in range(plies):
        node = tree.nodes.get(fen_key(b))
        if node is None:
            break
        mv = node.user_move if b.turn == user else (node.opponent_moves[0] if node.opponent_moves else None)
        if not mv or chess.Move.from_uci(mv) not in b.legal_moves:
            break
        out.append(mv)
        b.push_uci(mv)
    return out


def _annotate_line(start_fen: str, first: dict, rest: list[dict], user_color: bool, depth: int, max_marks: int = 3) -> None:
    """Add symbols to the user's own moves in ``rest`` (the opponent's moves stay plain)."""
    marks = 0
    for m in rest:
        board = chess.Board(m["fen_before"])
        if board.turn == user_color and marks < max_marks:
            try:
                a = annotate(m["fen_before"], m["uci"], depth=depth)
                m.update(kind=a["kind"], symbol=a["symbol"], label=a["label"])
                marks += 1
            except ValueError:
                pass


def compare(session, user_id: int, repertoire_id: int, fen: str, played: str, depth: int = 12) -> dict:
    tree = load_tree(session, repertoire_id)
    board = chess.Board(fen)
    key = fen_key(board)
    node = tree.nodes.get(key)
    user_color = chess.WHITE if tree.color == "white" else chess.BLACK
    rep_move = node.user_move if node and board.turn == user_color else None

    you = annotate(fen, played, depth=depth)
    after_played = board.copy()
    after_played.push_uci(played)
    cont, n_games = games_continuation(user_games(session, user_id), key, played)
    you["line"] = _san_moves(after_played.fen(), cont)
    _annotate_line(after_played.fen(), you, you["line"], user_color, depth)
    you["games"] = n_games

    rep = None
    if rep_move:
        rep = annotate(fen, rep_move, depth=depth, book=True)
        after_rep = board.copy()
        after_rep.push_uci(rep_move)
        rep["line"] = _san_moves(after_rep.fen(), tree_line(tree, after_rep))

    suggestion = None
    best = you["best_move"]
    if best:
        suggestion = annotate(fen, best, depth=depth, book=(best == rep_move))
        after_best = board.copy()
        after_best.push_uci(best)
        pv = engine.evaluate(after_best.fen(), depth=depth).lines
        suggestion["line"] = _san_moves(after_best.fen(), pv[0].pv_uci[:LINE_PLIES] if pv else [])

    return {"fen": fen, "color": tree.color, "repertoire_name": tree.name, "you": you, "repertoire": rep,
            "suggestion": suggestion, "same_as_repertoire": best == rep_move}
