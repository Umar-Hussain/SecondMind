"""Move quality symbols, in the style players know from chess sites.

Every label comes from Stockfish numbers, never from the LLM:

* ``book``       - the move is in the user's repertoire (practice mode, comparisons);
* ``brilliant``  - a best move that leaves a piece (knight or bigger) en prise: a real sacrifice;
* ``great``      - the best move when the second best is much worse (the only good move);
* ``best``       - within 10 centipawns of the engine's first choice;
* ``excellent``  - loses at most 30 cp;  ``good`` at most 60 cp;
* ``inaccuracy`` - loses at most 120 cp; ``mistake`` at most 250 cp; ``blunder`` more.

Loss is measured from the mover's point of view against the engine best.
"""

from __future__ import annotations

import chess

from app.tools import engine

SYMBOL = {"book": "📖", "brilliant": "!!", "great": "!", "best": "★", "excellent": "👍", "good": "✓",
          "inaccuracy": "?!", "mistake": "?", "blunder": "??"}
LABEL = {"book": "Book move", "brilliant": "Brilliant", "great": "Great move", "best": "Best move",
         "excellent": "Excellent", "good": "Good", "inaccuracy": "Inaccuracy", "mistake": "Mistake",
         "blunder": "Blunder"}
VALUE = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
ONLY_MOVE_GAP = 150  # cp between best and second best for "great"


def kind_for_loss(loss: int) -> str:
    if loss <= 10:
        return "best"
    if loss <= 30:
        return "excellent"
    if loss <= 60:
        return "good"
    if loss <= 120:
        return "inaccuracy"
    if loss <= 250:
        return "mistake"
    return "blunder"


def is_sacrifice(board: chess.Board, move: chess.Move) -> bool:
    """After ``move``, is a knight-or-bigger piece of the mover left to be won?

    "Won" = attacked and either undefended or attacked by a cheaper piece. Captures that
    simply take back equal material are not sacrifices.
    """
    mover = board.turn
    after = board.copy()
    after.push(move)
    for sq, piece in after.piece_map().items():
        if piece.color != mover or VALUE[piece.piece_type] < 3:
            continue
        attackers = after.attackers(not mover, sq)
        if not attackers:
            continue
        cheapest = min(VALUE[after.piece_at(a).piece_type] or 100 for a in attackers)
        defended = bool(after.attackers(mover, sq))
        if not defended or cheapest < VALUE[piece.piece_type]:
            captured = board.piece_at(move.to_square)
            gain = VALUE[captured.piece_type] if captured else 0
            if VALUE[piece.piece_type] > gain:
                return True
    return False


def annotate(fen: str, move_uci: str, depth: int | None = None, book: bool = False) -> dict:
    """Symbol, label and numbers for one move. ``book`` marks a repertoire move."""
    board = chess.Board(fen)
    move = chess.Move.from_uci(move_uci)
    if move not in board.legal_moves:
        raise ValueError(f"illegal move {move_uci}")
    ev = engine.evaluate(fen, depth=depth, multipv=2)
    best_cp = ev.cp_stm
    move_cp = next((line.cp for line in ev.lines if line.move_uci == move_uci), None)
    if move_cp is None:
        move_cp = engine.evaluate_moves(fen, [move_uci], depth=depth).get(move_uci, best_cp)
    loss = max(0, best_cp - move_cp)
    kind = kind_for_loss(loss)
    if kind == "best":
        second = ev.lines[1].cp if len(ev.lines) > 1 else None
        if is_sacrifice(board, move) and move_cp > -150:
            kind = "brilliant"
        elif second is not None and best_cp - second >= ONLY_MOVE_GAP and move_uci == ev.best_move_uci:
            kind = "great"
    if book and kind in ("best", "excellent", "good"):
        kind = "book"
    return {"move": move_uci, "san": board.san(move), "kind": kind, "symbol": SYMBOL[kind], "label": LABEL[kind],
            "loss_cp": loss, "cp": move_cp, "best_cp": best_cp, "best_move": ev.best_move_uci,
            "best_san": board.san(chess.Move.from_uci(ev.best_move_uci)) if ev.best_move_uci else None}
