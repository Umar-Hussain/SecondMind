"""Card preview used by the library grid and the study-style repertoire list."""

from app.tools.repertoire import import_pgn, preview

PGN = """[Event "Caro"]

1. e4 c6 2. d4 d5 3. e5 (3. Nc3 dxe4 4. Nxe4 Bf5) 3... Bf5 4. Nf3 e6 *
"""


def test_preview_lists_main_line_and_branches():
    tree = import_pgn(PGN, "black")
    p = preview(tree)
    assert p["key_move"] == "c6"  # black's first move
    assert p["main_line"].startswith("1.e4 c6 2.d4 d5 3.e5")
    assert len(p["chapters"]) == 2
    assert p["chapters"][1]["label"].startswith("3.Nc3")  # where the second line leaves the main line
    assert "Caro-Kann" in p["opening"]


def test_preview_of_empty_tree():
    tree = import_pgn("*", "white")
    p = preview(tree)
    assert p["chapters"] == [] and p["key_move"] == ""
