"""repertoire import, transpositions, validation and PGN round trip."""

import chess

from app.config import FIXTURES_DIR
from app.tools.pgn_utils import fen_key, san_line_to_uci
from app.tools.repertoire import (
    edit_node, export_pgn, import_moves_text, import_pgn, load_tree, save_tree,
)

WHITE_PGN = (FIXTURES_DIR / "repertoire_white.pgn").read_text()
BLACK_PGN = (FIXTURES_DIR / "repertoire_black.pgn").read_text()


def _key_after(moves: str) -> str:
    board = chess.Board()
    for u in san_line_to_uci(moves):
        board.push_uci(u)
    return fen_key(board)


def test_import_with_variations_and_comments() -> None:
    tree = import_pgn(WHITE_PGN, "white", "e4 as White")
    assert not tree.errors
    assert tree.get_user_move(_key_after("")) == "e2e4"
    assert set(tree.covered_opponent_moves(_key_after("e4"))) == {"e7e5", "c7c5", "c7c6", "e7e6"}
    assert tree.get_user_move(_key_after("e4 c6 d4 d5")) == "e4e5"
    assert "Ruy Lopez" in tree.nodes[_key_after("e4 e5 Nf3 Nc6")].comment


def test_transposition_maps_to_same_node() -> None:
    tree = import_pgn(BLACK_PGN, "black", "Caro-Kann")
    # Both move orders reach one key; the user move there comes from the 3.Nc3 line.
    a = _key_after("e4 c6 d4 d5 Nc3")
    b = _key_after("e4 c6 Nc3 d5 d4")
    assert a == b
    assert tree.get_user_move(b) == "d5e4"


def test_multi_game_pgn_merges_into_one_tree() -> None:
    tree = import_pgn(BLACK_PGN, "black")
    assert set(tree.covered_opponent_moves(_key_after(""))) == {"e2e4", "d2d4"}


def test_illegal_move_is_reported_precisely() -> None:
    bad = '[Event "x"]\n\n1. e4 e5 2. Nf3 Nf6 3. Bb5 Ke3 *'
    tree = import_pgn(bad, "white")
    assert tree.errors
    err = tree.errors[0]
    assert "Ke3" in err.message and "move 3 (Black)" in err.location


def test_moves_text_import_and_error() -> None:
    tree = import_moves_text("1.e4 c6 2.d4 d5 3.e5", "white", "Caro Advance")
    assert tree.get_user_move(_key_after("e4 c6 d4 d5")) == "e4e5"
    bad = import_moves_text("1.e4 c6 2.d5", "white")
    assert bad.errors and "move 2 (White)" in bad.errors[0].location


def test_several_user_moves_keeps_first_as_main() -> None:
    pgn = '[Event "x"]\n\n1. e4 e5 2. Nf3 (2. Bc4) *'
    tree = import_pgn(pgn, "white")
    node = tree.nodes[_key_after("e4 e5")]
    assert node.user_move == "g1f3" and node.alternatives == ["f1c4"]
    assert any(i.level == "warning" for i in tree.issues)


def test_color_mismatch_detected() -> None:
    tree = import_pgn(WHITE_PGN, "black")
    assert any("looks like a White repertoire" in i.message for i in tree.issues)
    assert not any("looks like" in i.message for i in import_pgn(WHITE_PGN, "white").issues)


def test_export_round_trip() -> None:
    tree = import_pgn(WHITE_PGN, "white", "e4")
    again = import_pgn(export_pgn(tree), "white", "e4")
    assert {k: (n.user_move, sorted(n.opponent_moves)) for k, n in tree.nodes.items()} == \
           {k: (n.user_move, sorted(n.opponent_moves)) for k, n in again.nodes.items()}


def test_save_load_and_edit(db) -> None:
    tree = import_pgn(WHITE_PGN, "white", "e4")
    rep = save_tree(db, None, tree, "pgn", WHITE_PGN)
    loaded = load_tree(db, rep.id)
    assert loaded.nodes.keys() == tree.nodes.keys()
    key = _key_after("e4 d5")  # Scandinavian not covered yet
    edit_node(db, rep.id, _key_after("e4"), add_opponent_move="d7d5")
    edit_node(db, rep.id, key, user_move="e4d5")
    loaded = load_tree(db, rep.id)
    assert "d7d5" in loaded.covered_opponent_moves(_key_after("e4"))
    assert loaded.get_user_move(key) == "e4d5"
