"""Phase 4: ECO classification."""

from app.tools.openings import classify, family, gambit_entries
from app.tools.pgn_utils import san_line_to_uci


def test_najdorf_is_recognised() -> None:
    moves = san_line_to_uci("e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6")
    info = classify(moves)
    assert info.eco == "B90"
    assert "Najdorf" in info.name
    assert info.ply_last_known == 10


def test_deepest_entry_wins_after_leaving_book() -> None:
    moves = san_line_to_uci("e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7 Re1 b5")
    info = classify(moves)
    assert info.name.startswith("Ruy Lopez")
    assert info.ply_last_known == 10


def test_transposition_is_classified_by_position() -> None:
    # 1.e4 c6 2.Nc3 d5 3.d4 reaches the same position as 2.d4 d5 3.Nc3
    info = classify(san_line_to_uci("e4 c6 Nc3 d5 d4"))
    assert info.eco == "B15"


def test_gambit_candidates_and_family() -> None:
    names = [n for _, n, _ in gambit_entries()]
    assert any("King's Gambit" in n for n in names)
    assert family("Sicilian Defense: Najdorf Variation") == "Sicilian Defense"
