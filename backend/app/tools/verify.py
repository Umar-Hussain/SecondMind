"""Verification guard (spec 7, 8.7, Phase 10).

Hard rule: no move, evaluation or citation produced by the LLM reaches the
user unless this guard passes. Pipelines retry the model once with the
reasons returned here, then drop the item.

Checks

* ``is_legal`` — python-chess legality (SAN or UCI).
* ``verify_line`` — a whole sequence is legal; returns the final FEN.
* ``verify_recommendation`` — legal and within ``max_loss_cp`` of the engine
  best (or of the best *gambit-keeping* move when ``reference_moves`` is given).
* ``verify_citations`` — every cited id exists in the retrieved set.
* ``verify_text_moves`` — every move-like token in free text is one of the
  moves the tools actually supplied (used for explanations and chat answers).
"""

from __future__ import annotations

import re
from collections.abc import Iterable

import chess

from app.schemas import RetrievedDoc, VerificationResult
from app.tools import engine

# SAN-like tokens: Nf3, exd5, O-O, e8=Q+, Qxd7#, also "12.Nf3" / "12...Nf6" prefixes.
SAN_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:\d+\.(?:\.\.)?\s?)?"
    r"(O-O-O|O-O|[KQRBN][a-h]?[1-8]?x?[a-h][1-8]|[a-h]x[a-h][1-8](?:=[QRBN])?|[a-h][1-8](?:=[QRBN])?)"
    r"[+#]?(?![A-Za-z0-9])"
)
UCI_RE = re.compile(r"(?<![A-Za-z0-9])([a-h][1-8][a-h][1-8][qrbn]?)(?![A-Za-z0-9])")
CITE_RE = re.compile(r"\[((?:idea|game)-[A-Za-z0-9-]+)\]")


def _board(fen: str) -> chess.Board:
    return chess.Board(fen) if len(fen.split()) >= 6 else chess.Board(fen + " 0 1")


def parse_move(board: chess.Board, move: str) -> chess.Move | None:
    """Accept UCI or SAN; return the legal Move or None."""
    move = move.strip()
    try:
        m = chess.Move.from_uci(move)
        if m in board.legal_moves:
            return m
    except ValueError:
        pass
    try:
        return board.parse_san(move)
    except ValueError:
        return None


def is_legal(fen: str, move: str) -> bool:
    return parse_move(_board(fen), move) is not None


def verify_line(fen: str, moves: Iterable[str]) -> VerificationResult:
    board = _board(fen)
    for i, mv in enumerate(moves, start=1):
        m = parse_move(board, mv)
        if m is None:
            return VerificationResult(ok=False, reasons=[f"move {i} '{mv}' is illegal in {board.fen()}"])
        board.push(m)
    return VerificationResult(ok=True, corrected=board.fen())


def verify_recommendation(fen: str, move: str, max_loss_cp: int = 40, depth: int | None = None,
                          reference_moves: list[str] | None = None) -> VerificationResult:
    board = _board(fen)
    m = parse_move(board, move)
    if m is None:
        return VerificationResult(ok=False, reasons=[f"'{move}' is illegal in this position"])
    if reference_moves:
        pool = sorted({*reference_moves, m.uci()})
        scores = engine.evaluate_moves(board.fen(), pool, depth=depth)
        best = max(scores.values())
        loss = best - scores[m.uci()]
        ref = "the best gambit-keeping move"
    else:
        loss = engine.eval_loss(board.fen(), m.uci(), depth=depth)
        ref = "the engine best"
    if loss > max_loss_cp:
        return VerificationResult(ok=False, reasons=[f"{board.san(m)} loses {loss} cp versus {ref} "
                                                     f"(limit {max_loss_cp})"])
    return VerificationResult(ok=True, corrected=m.uci())


def cited_ids(text: str) -> list[str]:
    return CITE_RE.findall(text)


def verify_citations(text_or_ids: str | Iterable[str], retrieved_docs: Iterable[RetrievedDoc | str]
                     ) -> VerificationResult:
    """Every citation id (``[idea-...]`` in text, or a list of ids) must be in the retrieved set."""
    ids = cited_ids(text_or_ids) if isinstance(text_or_ids, str) else list(text_or_ids)
    allowed = {d.id if isinstance(d, RetrievedDoc) else d for d in retrieved_docs}
    missing = [i for i in ids if i not in allowed]
    if missing:
        return VerificationResult(ok=False, reasons=[f"citation '{i}' was not retrieved" for i in missing])
    return VerificationResult(ok=True)


def extract_moves(text: str) -> list[str]:
    """Move-like tokens (SAN and UCI) mentioned in free text."""
    sans = [m.group(1) for m in SAN_RE.finditer(text)]
    ucis = UCI_RE.findall(text)
    return sans + ucis


def _norm(san: str) -> str:
    return san.rstrip("+#").replace("0-0-0", "O-O-O").replace("0-0", "O-O")


def unverified_moves(text: str, allowed: Iterable[str]) -> list[str]:
    """Move-like tokens in ``text`` that no tool supplied (the guard's exact rule).

    A bare square such as "e5" is allowed when it is the destination square of a
    supplied move, because prose like "the pawn on e5" names squares. Known limit:
    such a token could also be an unverified pawn move to that square.
    """
    allowed_set = {_norm(a) for a in allowed}
    allowed_squares = {a[-2:] for a in allowed_set if len(a) >= 2}
    bad = [mv for mv in extract_moves(text) if _norm(mv) not in allowed_set]
    return [b for b in bad if not (len(b) == 2 and b in allowed_squares)]


def verify_text_moves(text: str, allowed: Iterable[str]) -> VerificationResult:
    """Every move token in ``text`` must be one the tools supplied (SAN or UCI)."""
    bad = unverified_moves(text, allowed)
    if bad:
        return VerificationResult(ok=False, reasons=[f"unverified move '{b}' in text" for b in sorted(set(bad))])
    return VerificationResult(ok=True)


def allowed_moves_for(fen: str, ucis: Iterable[str]) -> set[str]:
    """SAN and UCI spellings of moves from one position (helper to build ``allowed``)."""
    board = _board(fen)
    out: set[str] = set()
    for u in ucis:
        m = parse_move(board, u)
        if m:
            out |= {m.uci(), board.san(m)}
    return out


def allowed_line(fen: str, ucis: Iterable[str]) -> set[str]:
    """SAN and UCI spellings for every move of a line played from ``fen``."""
    board = _board(fen)
    out: set[str] = set()
    for u in ucis:
        m = parse_move(board, u)
        if m is None:
            break
        out |= {m.uci(), board.san(m)}
        board.push(m)
    return out
