"""ECO opening classification (spec Phase 4).

Builds a lookup from *position* (board part of the FEN plus side to move) to
the deepest ECO entry reaching that position, then walks a game and keeps the
last position that matches. Keying by position (not by move string) means a
game that transposes into a known opening is still classified correctly.

Data: the Lichess ``chess-openings`` tables (``a.tsv``..``e.tsv``) when they
have been downloaded into ``backend/data/eco/`` with
``python scripts/download_eco.py``; otherwise a curated bundled subset
(``bundled.tsv``) that covers the openings used in fixtures and tests.
"""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

import chess

from app.config import DATA_DIR
from app.schemas import OpeningInfo

ECO_DIR = DATA_DIR / "eco"


def _pos_key(board: chess.Board) -> str:
    # Board + side to move is enough for opening identity.
    return board.board_fen() + (" w" if board.turn else " b")


def _eco_files() -> list[Path]:
    full = [ECO_DIR / f"{c}.tsv" for c in "abcde"]
    if all(p.exists() for p in full):
        return full
    return [ECO_DIR / "bundled.tsv"]


@lru_cache(maxsize=1)
def _table() -> dict[str, tuple[str, str, int]]:
    """position key -> (eco, name, ply). Deeper entries overwrite shallower ones."""
    table: dict[str, tuple[str, str, int]] = {}
    for path in _eco_files():
        with path.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                board = chess.Board()
                ply = 0
                ok = True
                for tok in row["pgn"].split():
                    if tok.endswith("."):
                        continue
                    try:
                        board.push_san(tok)
                    except ValueError:
                        ok = False
                        break
                    ply += 1
                if not ok:
                    continue
                key = _pos_key(board)
                prev = table.get(key)
                if prev is None or ply >= prev[2]:
                    table[key] = (row["eco"], row["name"], ply)
    return table


def classify(moves_uci: list[str]) -> OpeningInfo:
    """Return the deepest recognised ECO opening reached by the move list."""
    table = _table()
    board = chess.Board()
    best = OpeningInfo(eco="A00", name="Unknown Opening", ply_last_known=0)
    for ply, uci in enumerate(moves_uci, start=1):
        try:
            board.push_uci(uci)
        except ValueError:
            break
        hit = table.get(_pos_key(board))
        if hit:
            best = OpeningInfo(eco=hit[0], name=hit[1], ply_last_known=ply)
        if ply >= 40:  # openings never run longer than this
            break
    return best


def lookup_position(board: chess.Board) -> tuple[str, str] | None:
    """(eco, name) if this exact position is an ECO entry."""
    hit = _table().get(_pos_key(board))
    return (hit[0], hit[1]) if hit else None


def gambit_entries() -> list[tuple[str, str, int]]:
    """Every ECO entry whose name contains 'Gambit' (candidate gambits, spec 8.3)."""
    return sorted({v for v in _table().values() if "Gambit" in v[1]})


def family(name: str) -> str:
    """Opening family, e.g. 'Sicilian Defense: Najdorf Variation' -> 'Sicilian Defense'."""
    return name.split(":")[0].strip()
