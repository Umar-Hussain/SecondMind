"""Repertoire search for the Library and "My repertoires".

One query box understands three kinds of input:

* **move sequences** (``1.e4 c6 2.d4`` or ``e4 c6 d4``): matches repertoires whose
  tree contains every move of the line. Positions are looked up by key, so a line
  reached through a transposition still matches;
* **ECO codes** (``B12``): matches repertoires that reach an opening with that code;
* **words** (``caro advance``): every word must appear in the name, description,
  colour, or the names of the openings the repertoire reaches.

Opening names come from the ECO table, so a repertoire called "My Black stuff" is
still found by "Caro-Kann" if it contains Caro-Kann positions.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable

import chess
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Repertoire, RepertoireNode
from app.tools.openings import lookup_position
from app.tools.pgn_utils import board_from_key, fen_key

_MOVE_NO = re.compile(r"^\d+\.+")
_ECO = re.compile(r"^[a-e]\d\d$", re.I)


def parse_line(query: str) -> list[str] | None:
    """UCI moves if the whole query is a legal move sequence from the start, else None."""
    tokens = [_MOVE_NO.sub("", t) for t in query.replace(",", " ").split()]
    tokens = [t for t in tokens if t]
    if not tokens:
        return None
    board, ucis = chess.Board(), []
    for tok in tokens:
        try:
            move = board.parse_san(tok)
        except ValueError:
            return None
        ucis.append(move.uci())
        board.push(move)
    return ucis


def _node_moves(n: RepertoireNode) -> set[str]:
    return {m for m in [n.user_move_uci, *(n.alternative_moves_json or []), *(n.opponent_moves_json or [])] if m}


def _contains_line(nodes: dict[str, RepertoireNode], ucis: list[str]) -> bool:
    board = chess.Board()
    for u in ucis:
        node = nodes.get(fen_key(board))
        stored = node is not None and u in _node_moves(node)
        board.push_uci(u)
        # A move that is not stored still counts when it transposes into a stored position.
        if not stored and fen_key(board) not in nodes:
            return False
    return True


def _openings(nodes: Iterable[RepertoireNode]) -> set[tuple[str, str]]:
    found = set()
    for n in nodes:
        hit = lookup_position(board_from_key(n.fen_key))
        if hit:
            found.add(hit)
    return found


def search(session: Session, reps: list[Repertoire], query: str) -> list[tuple[Repertoire, str]]:
    """Filter ``reps`` by ``query``; returns (repertoire, why it matched)."""
    q = query.strip()
    if not q or not reps:
        return [(r, "") for r in reps]
    by_rep: dict[int, dict[str, RepertoireNode]] = defaultdict(dict)
    for n in session.scalars(select(RepertoireNode).where(RepertoireNode.repertoire_id.in_([r.id for r in reps]))):
        by_rep[n.repertoire_id][n.fen_key] = n

    line = parse_line(q)
    if line is not None:
        board = chess.Board()
        sans = []
        for u in line:
            sans.append(board.san(chess.Move.from_uci(u)))
            board.push_uci(u)
        label = f"contains {' '.join(sans)}"
        return [(r, label) for r in reps if _contains_line(by_rep[r.id], line)]

    words = q.lower().split()
    out = []
    for r in reps:
        openings = _openings(by_rep[r.id].values())
        if len(words) == 1 and _ECO.match(words[0]):
            names = sorted(name for eco, name in openings if eco.lower() == words[0])
            if names:
                out.append((r, f"reaches {names[0]}"))
            continue
        own_text = " ".join([r.name, r.description or "", r.color]).lower()
        opening_text = " ".join(f"{eco} {name}" for eco, name in openings).lower()
        if all(w in own_text or w in opening_text for w in words):
            why = ""
            if not all(w in own_text for w in words):
                hits = sorted(name for _, name in openings if any(w in name.lower() for w in words))
                why = f"reaches {hits[0]}" if hits else ""
            out.append((r, why))
    return out
