"""Small python-chess helpers used across the tools.

Keeping FEN normalisation and SAN/UCI conversion in one place avoids the most
common bug in this domain: two modules disagreeing on what "the same position"
means.
"""

from __future__ import annotations

import io
import re

import chess
import chess.pgn

_CLK_RE = re.compile(r"\[%clk\s+(\d+):(\d+):(\d+(?:\.\d+)?)\]")


def fen_key(board_or_fen: chess.Board | str) -> str:
    """Normalized position key: the first four FEN fields.

    pieces, side to move, castling rights and en-passant square — but not the
    move counters, so the same position reached by different move orders
    (a transposition) gets the same key (spec 8.8).
    """
    fen = board_or_fen.fen() if isinstance(board_or_fen, chess.Board) else board_or_fen
    board = chess.Board(fen) if fen.count(" ") >= 3 and len(fen.split()) >= 4 else None
    if board is None:
        return fen
    # Only keep the en-passant square when a capture is actually possible,
    # otherwise "e3" vs "-" would split identical positions.
    ep = chess.square_name(board.ep_square) if board.ep_square and board.has_legal_en_passant() else "-"
    parts = board.fen().split()
    return " ".join([parts[0], parts[1], parts[2], ep])


def board_from_key(key: str) -> chess.Board:
    """Rebuild a board from a fen_key (move counters set to defaults)."""
    return chess.Board(key + " 0 1") if len(key.split()) == 4 else chess.Board(key)


def uci_to_san(fen: str, uci: str) -> str:
    """SAN for one move, or the UCI string back if it is illegal."""
    board = chess.Board(fen) if len(fen.split()) >= 6 else board_from_key(fen)
    try:
        move = chess.Move.from_uci(uci)
    except ValueError:
        return uci
    return board.san(move) if move in board.legal_moves else uci


def line_to_san(fen: str, ucis: list[str]) -> list[str]:
    """SAN for a sequence of moves starting at ``fen`` (stops at the first illegal move)."""
    board = chess.Board(fen) if len(fen.split()) >= 6 else board_from_key(fen)
    out: list[str] = []
    for u in ucis:
        try:
            move = chess.Move.from_uci(u)
        except ValueError:
            break
        if move not in board.legal_moves:
            break
        out.append(board.san(move))
        board.push(move)
    return out


def san_line_to_uci(moves_san: list[str] | str, start: chess.Board | None = None) -> list[str]:
    board = start.copy() if start else chess.Board()
    if isinstance(moves_san, str):
        moves_san = [m for m in moves_san.split() if not m.endswith(".")]
    out = []
    for san in moves_san:
        move = board.parse_san(san)
        out.append(move.uci())
        board.push(move)
    return out


def read_pgn_games(pgn_text: str) -> list[chess.pgn.Game]:
    """Parse every game in a (possibly multi-game) PGN string."""
    stream = io.StringIO(pgn_text)
    games = []
    while True:
        game = chess.pgn.read_game(stream)
        if game is None:
            break
        games.append(game)
    return games


def mainline_uci_and_clocks(game: chess.pgn.Game) -> tuple[list[str], list[float] | None]:
    """UCI move list plus clock (seconds) after each ply if ``[%clk]`` comments exist."""
    moves, clocks = [], []
    for node in game.mainline():
        moves.append(node.move.uci())
        m = _CLK_RE.search(node.comment or "")
        if m:
            h, mi, s = m.groups()
            clocks.append(int(h) * 3600 + int(mi) * 60 + float(s))
    return moves, (clocks if len(clocks) == len(moves) and clocks else None)


def player_result(result_tag: str, color: str) -> str:
    """Translate a PGN result tag into win/draw/loss for ``color``."""
    if result_tag == "1/2-1/2":
        return "draw"
    if result_tag == "1-0":
        return "win" if color == "white" else "loss"
    if result_tag == "0-1":
        return "win" if color == "black" else "loss"
    return "draw"


def material_balance(board: chess.Board, color: chess.Color) -> int:
    """Material for ``color`` minus opponent, in pawns (P=1 N=B=3 R=5 Q=9)."""
    values = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}
    score = 0
    for piece, v in values.items():
        score += v * (len(board.pieces(piece, color)) - len(board.pieces(piece, not color)))
    return score
