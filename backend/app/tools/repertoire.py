"""Repertoire import, position-keyed tree and validation (spec 5.1.1, 8.8, Phase 7).

The tree is keyed by **normalized position** (first four FEN fields), never by
move path, so two move orders reaching the same position share one node and
transpositions are recognised automatically (spec B5 pitfall).

Each node stores:

* ``user_move`` — the repertoire's main move when it is the user's turn,
* ``alternatives`` — further user moves found at that position,
* ``opponent_moves`` — opponent replies the repertoire covers,
* ``comment`` — merged PGN comments.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

import chess
import chess.pgn
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Repertoire, RepertoireNode
from app.tools.pgn_utils import fen_key

START_KEY = fen_key(chess.Board())


@dataclass
class Node:
    fen_key: str
    user_move: str | None = None
    alternatives: list[str] = field(default_factory=list)
    opponent_moves: list[str] = field(default_factory=list)
    comment: str = ""
    parent: str | None = None

    def user_moves(self) -> list[str]:
        return ([self.user_move] if self.user_move else []) + self.alternatives


@dataclass
class ImportIssue:
    level: str  # error | warning
    location: str  # e.g. "game 1, move 3 (White)"
    message: str


@dataclass
class RepTree:
    color: str
    name: str = ""
    nodes: dict[str, Node] = field(default_factory=dict)
    issues: list[ImportIssue] = field(default_factory=list)

    @property
    def user_turn(self) -> chess.Color:
        return chess.WHITE if self.color == "white" else chess.BLACK

    # --- queries (spec Phase 7 step 5) ------------------------------------
    def is_in_tree(self, key: str) -> bool:
        return key in self.nodes

    def get_user_move(self, key: str) -> str | None:
        node = self.nodes.get(key)
        return node.user_move if node else None

    def covered_opponent_moves(self, key: str) -> list[str]:
        node = self.nodes.get(key)
        return list(node.opponent_moves) if node else []

    @property
    def errors(self) -> list[ImportIssue]:
        return [i for i in self.issues if i.level == "error"]

    # --- building ------------------------------------------------------------
    def _node(self, key: str, parent: str | None) -> Node:
        node = self.nodes.get(key)
        if node is None:
            node = Node(fen_key=key, parent=parent)
            self.nodes[key] = node
        return node

    def add_move(self, board: chess.Board, move: chess.Move, comment: str = "", parent: str | None = None,
                 location: str = "") -> None:
        """Register ``move`` played from ``board`` (board is NOT modified)."""
        key = fen_key(board)
        node = self._node(key, parent)
        uci = move.uci()
        if board.turn == self.user_turn:
            if node.user_move is None:
                node.user_move = uci
            elif uci != node.user_move and uci not in node.alternatives:
                node.alternatives.append(uci)
                self.issues.append(ImportIssue(
                    "warning", location,
                    f"several repertoire moves in one position: keeping {board.san(chess.Move.from_uci(node.user_move))}"
                    f" as main move and {board.san(move)} as an alternative"))
        elif uci not in node.opponent_moves:
            node.opponent_moves.append(uci)
        if comment:
            node.comment = (node.comment + " " + comment).strip()
        # Ensure the child exists so leaf positions are "in the tree".
        child = board.copy()
        child.push(move)
        self._node(fen_key(child), key)


def _location(game_no: int, board: chess.Board) -> str:
    side = "White" if board.turn == chess.WHITE else "Black"
    return f"game {game_no}, move {board.fullmove_number} ({side})"


_ILLEGAL_RE = re.compile(r"(illegal|invalid|ambiguous) san: '([^']+)' in (\S+ \S+ \S+ \S+ \S+ \S+)")


def import_pgn(pgn_text: str, color: str, name: str = "") -> RepTree:
    """Parse every game and every variation into one position-keyed tree."""
    tree = RepTree(color=color, name=name)
    stream = io.StringIO(pgn_text)
    game_no = 0
    while True:
        game = chess.pgn.read_game(stream)
        if game is None:
            break
        game_no += 1
        # python-chess records illegal moves in game.errors and stops that variation.
        for err in game.errors:
            m = _ILLEGAL_RE.search(str(err))
            if m:
                board = chess.Board(m.group(3))
                tree.issues.append(ImportIssue("error", _location(game_no, board),
                                               f"{m.group(1)} move '{m.group(2)}'"))
            else:
                tree.issues.append(ImportIssue("error", f"game {game_no}", str(err)))

        def walk(node: chess.pgn.GameNode, board: chess.Board, parent: str | None) -> None:
            for child in node.variations:
                comment = (child.comment or "").strip()
                tree.add_move(board, child.move, comment, parent, _location(game_no, board))
                nxt = board.copy()
                nxt.push(child.move)
                walk(child, nxt, fen_key(board))

        walk(game, game.board(), None)

    if game_no == 0:
        tree.issues.append(ImportIssue("error", "file", "no games found in the PGN"))
    _check_color(tree)
    return tree


def _check_color(tree: RepTree) -> None:
    """Flag a repertoire whose moves look like they belong to the other color.

    A real repertoire branches on the *opponent's* moves (you prepare against
    several replies) and rarely on your own. If every branch is on the user's
    side and none on the opponent's, the color is almost certainly wrong.
    """
    user_branching = sum(1 for n in tree.nodes.values() if n.alternatives)
    opp_branching = sum(1 for n in tree.nodes.values() if len(n.opponent_moves) > 1)
    if user_branching >= 1 and opp_branching == 0:
        other = "Black" if tree.color == "white" else "White"
        tree.issues.append(ImportIssue(
            "warning", "whole file",
            f"all variations branch on {tree.color.capitalize()}'s moves and none on the opponent's: "
            f"this looks like a {other} repertoire"))


_MOVE_NO = re.compile(r"^\d+\.+$")
_MOVE_NO_PREFIX = re.compile(r"^\d+\.+")


def import_moves_text(text: str, color: str, name: str = "") -> RepTree:
    """Plain move list, e.g. ``1.e4 c6 2.d4 d5 3.e5`` (one line)."""
    tree = RepTree(color=color, name=name)
    board = chess.Board()
    parent = None
    for raw in text.replace("\n", " ").split():
        if _MOVE_NO.match(raw) or raw in ("*", "1-0", "0-1", "1/2-1/2"):
            continue
        tok = _MOVE_NO_PREFIX.sub("", raw)
        try:
            move = board.parse_san(tok)
        except ValueError:
            tree.issues.append(ImportIssue("error", _location(1, board), f"illegal move '{tok}'"))
            break
        tree.add_move(board, move, parent=parent, location=_location(1, board))
        parent = fen_key(board)
        board.push(move)
    _check_color(tree)
    return tree


def import_lichess_study(url: str, color: str, name: str = "") -> RepTree:
    from app.tools.lichess import export_study_pgn

    return import_pgn(export_study_pgn(url), color, name)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def export_pgn(tree: RepTree) -> str:
    """Write the tree back to PGN (depth-first, transpositions written once)."""
    game = chess.pgn.Game()
    game.headers["Event"] = tree.name or f"Repertoire ({tree.color})"
    visited: set[str] = set()

    def walk(pgn_node: chess.pgn.GameNode, board: chess.Board) -> None:
        key = fen_key(board)
        if key in visited:
            return
        visited.add(key)
        node = tree.nodes.get(key)
        if node is None:
            return
        moves = node.user_moves() if board.turn == tree.user_turn else node.opponent_moves
        for uci in moves:
            move = chess.Move.from_uci(uci)
            child = pgn_node.add_variation(move)
            nxt = board.copy()
            nxt.push(move)
            nkey = fen_key(nxt)
            if nkey in tree.nodes and tree.nodes[nkey].comment:
                pass
            walk(child, nxt)
        if node.comment and pgn_node.parent is not None:
            pgn_node.comment = node.comment

    walk(game, chess.Board())
    return str(game)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def save_tree(session: Session, user_id: int | None, tree: RepTree, source_type: str, raw_pgn: str = "",
              intentional_gambit: bool = False, status: str = "active") -> Repertoire:
    rep = Repertoire(user_id=user_id, name=tree.name or f"{tree.color} repertoire", color=tree.color,
                     source_type=source_type, raw_pgn=raw_pgn or export_pgn(tree),
                     intentional_gambit=intentional_gambit, status=status)
    session.add(rep)
    session.flush()
    for node in tree.nodes.values():
        session.add(RepertoireNode(repertoire_id=rep.id, fen_key=node.fen_key, user_move_uci=node.user_move,
                                   alternative_moves_json=node.alternatives,
                                   opponent_moves_json=node.opponent_moves, comment=node.comment,
                                   parent_fen_key=node.parent))
    session.commit()
    return rep


def load_tree(session: Session, repertoire_id: int) -> RepTree:
    rep = session.get(Repertoire, repertoire_id)
    if rep is None:
        raise KeyError(f"repertoire {repertoire_id} not found")
    tree = RepTree(color=rep.color, name=rep.name)
    for row in session.scalars(select(RepertoireNode).where(RepertoireNode.repertoire_id == repertoire_id)):
        tree.nodes[row.fen_key] = Node(fen_key=row.fen_key, user_move=row.user_move_uci,
                                       alternatives=list(row.alternative_moves_json or []),
                                       opponent_moves=list(row.opponent_moves_json or []),
                                       comment=row.comment or "", parent=row.parent_fen_key)
    return tree


def edit_node(session: Session, repertoire_id: int, key: str, *, user_move: str | None = None,
              add_alternative: str | None = None, add_opponent_move: str | None = None,
              comment: str | None = None) -> RepertoireNode:
    """Edit one node (PATCH /repertoires/{id}/nodes). Every move is legality-checked."""
    rep = session.get(Repertoire, repertoire_id)
    if rep is None:
        raise KeyError(f"repertoire {repertoire_id} not found")
    row = session.scalars(select(RepertoireNode).where(RepertoireNode.repertoire_id == repertoire_id,
                                                       RepertoireNode.fen_key == key)).first()
    if row is None:
        row = RepertoireNode(repertoire_id=repertoire_id, fen_key=key, alternative_moves_json=[],
                             opponent_moves_json=[], comment="")
        session.add(row)
    board = chess.Board(key + " 0 1")
    user_turn = (board.turn == chess.WHITE) == (rep.color == "white")

    def legal(u: str) -> str:
        if chess.Move.from_uci(u) not in board.legal_moves:
            raise ValueError(f"illegal move {u} in this position")
        return u

    if user_move is not None:
        if not user_turn:
            raise ValueError("it is the opponent's turn in this position")
        row.user_move_uci = legal(user_move)
    if add_alternative:
        if not user_turn:
            raise ValueError("it is the opponent's turn in this position")
        row.alternative_moves_json = [*(row.alternative_moves_json or []), legal(add_alternative)]
    if add_opponent_move:
        if user_turn:
            raise ValueError("it is your turn in this position")
        row.opponent_moves_json = [*(row.opponent_moves_json or []), legal(add_opponent_move)]
    if comment is not None:
        row.comment = comment
    # Make sure the child position exists so matching can continue through it.
    for u in filter(None, [user_move, add_alternative, add_opponent_move]):
        child = board.copy()
        child.push_uci(u)
        ck = fen_key(child)
        exists = session.scalars(select(RepertoireNode).where(RepertoireNode.repertoire_id == repertoire_id,
                                                              RepertoireNode.fen_key == ck)).first()
        if exists is None:
            session.add(RepertoireNode(repertoire_id=repertoire_id, fen_key=ck, parent_fen_key=key,
                                       alternative_moves_json=[], opponent_moves_json=[], comment=""))
    session.commit()
    return row


def tree_to_json(tree: RepTree) -> dict:
    """Serialisable view for the web app (nodes with SAN labels)."""
    out = []
    for node in tree.nodes.values():
        board = chess.Board(node.fen_key + " 0 1")

        def san(u: str) -> str:
            return board.san(chess.Move.from_uci(u))

        out.append({
            "fen_key": node.fen_key,
            "fen": node.fen_key + " 0 1",
            "user_move": node.user_move,
            "user_move_san": san(node.user_move) if node.user_move else None,
            "alternatives": [{"uci": u, "san": san(u)} for u in node.alternatives],
            "opponent_moves": [{"uci": u, "san": san(u)} for u in node.opponent_moves],
            "comment": node.comment,
            "parent": node.parent,
        })
    return {"color": tree.color, "name": tree.name, "root": START_KEY, "nodes": out}


# ---------------------------------------------------------------------------
# Library and editing helpers
# ---------------------------------------------------------------------------


def copy_repertoire(session: Session, source_id: int, user_id: int, name: str | None = None) -> Repertoire:
    """Copy a (library) repertoire into a user's own, editable repertoire."""
    src = session.get(Repertoire, source_id)
    if src is None:
        raise KeyError(f"repertoire {source_id} not found")
    tree = load_tree(session, source_id)
    tree.name = name or src.name
    rep = save_tree(session, user_id, tree, "library", src.raw_pgn, src.intentional_gambit)
    rep.copied_from_id = src.id
    rep.description = src.description
    session.commit()
    return rep


def _reachable(session: Session, repertoire_id: int, color: str) -> set[str]:
    """Positions reachable from the start through stored moves (transpositions included)."""
    rows = {r.fen_key: r for r in session.scalars(select(RepertoireNode)
                                                    .where(RepertoireNode.repertoire_id == repertoire_id))}
    seen: set[str] = set()
    stack = [START_KEY]
    while stack:
        key = stack.pop()
        if key in seen or key not in rows:
            continue
        seen.add(key)
        row = rows[key]
        board = chess.Board(key + " 0 1")
        moves = [m for m in [row.user_move_uci, *(row.alternative_moves_json or []),
                             *(row.opponent_moves_json or [])] if m]
        for u in moves:
            child = board.copy()
            child.push_uci(u)
            stack.append(fen_key(child))
    return seen


def remove_move(session: Session, repertoire_id: int, key: str, move: str) -> int:
    """Remove one move from a position and prune branches that are no longer reachable.

    Returns the number of positions deleted. Removing the main user move promotes the
    first alternative, if any.
    """
    rep = session.get(Repertoire, repertoire_id)
    if rep is None:
        raise KeyError(f"repertoire {repertoire_id} not found")
    row = session.scalars(select(RepertoireNode).where(RepertoireNode.repertoire_id == repertoire_id,
                                                       RepertoireNode.fen_key == key)).first()
    if row is None:
        raise ValueError("position is not in this repertoire")
    alts = list(row.alternative_moves_json or [])
    opps = list(row.opponent_moves_json or [])
    if row.user_move_uci == move:
        row.user_move_uci = alts.pop(0) if alts else None
    elif move in alts:
        alts.remove(move)
    elif move in opps:
        opps.remove(move)
    else:
        raise ValueError("that move is not stored in this position")
    row.alternative_moves_json, row.opponent_moves_json = alts, opps
    session.flush()
    keep = _reachable(session, repertoire_id, rep.color)
    removed = 0
    for node in session.scalars(select(RepertoireNode).where(RepertoireNode.repertoire_id == repertoire_id)):
        if node.fen_key not in keep:
            session.delete(node)
            removed += 1
    session.commit()
    return removed


def delete_repertoire(session: Session, repertoire_id: int) -> None:
    """Delete a repertoire and its rows. Children go first, as explicit ordered statements,
    so databases that enforce foreign keys (Postgres) accept it."""
    from sqlalchemy import delete

    from app.models import RepertoireDeviation, UncoveredLine

    for model in (RepertoireNode, RepertoireDeviation, UncoveredLine):
        session.execute(delete(model).where(model.repertoire_id == repertoire_id))
    session.execute(delete(Repertoire).where(Repertoire.id == repertoire_id))
    session.commit()
