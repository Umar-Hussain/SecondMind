"""Phase 8: repertoire deviation analysis and ranking on the fixtures."""

import pytest

from app.config import FIXTURES_DIR
from app.schemas import NormalizedGame
from app.tools import chesscom, lichess
from app.tools.deviations import analyze_repertoire, load_deviations, match_game, store_results
from app.tools.games import merge_games
from app.tools.pgn_utils import san_line_to_uci
from app.tools.repertoire import import_pgn

WHITE = import_pgn((FIXTURES_DIR / "repertoire_white.pgn").read_text(), "white", "e4")
BLACK = import_pgn((FIXTURES_DIR / "repertoire_black.pgn").read_text(), "black", "Caro")
DEPTH = 12


def _g(moves: str, color: str, gid: str = "x") -> NormalizedGame:
    return NormalizedGame(source="lichess", external_id=gid, pgn="", color=color, result="draw",
                          opponent="o", moves_uci=san_line_to_uci(moves))


def _games():
    return merge_games(lichess.fetch_games("demo_player"), chesscom.fetch_games("demo_player_cc"))


# --- Matching (no engine) -----------------------------------------------------


def test_in_book_game_has_no_deviation() -> None:
    assert match_game(_g("e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7", "white"), WHITE).kind == "in_book"


def test_user_deviation_detected() -> None:
    m = match_game(_g("e4 e5 Nf3 Nc6 Bc4 Bc5", "white"), WHITE)
    assert m.kind == "user_deviation" and m.played == "f1c4" and m.repertoire_move == "f1b5"


def test_uncovered_line_is_not_a_user_error() -> None:
    m = match_game(_g("e4 d5 exd5 Qxd5", "white"), WHITE)
    assert m.kind == "uncovered" and m.played == "d7d5"


def test_transposition_keeps_matching() -> None:
    m = match_game(_g("e4 c6 Nc3 d5 d4 dxe4 Nxe4 Bf5 Ng3", "black"), BLACK)
    assert m.kind == "in_book" and m.transposed


def test_ranking_by_game_count_without_engine() -> None:
    devs, unc = analyze_repertoire(_games(), WHITE, judge=False)
    counts = [d.games_count for d in devs]
    assert counts == sorted(counts, reverse=True)
    top = devs[0]
    assert (top.played_san, top.games_count) == ("Bc4", 5)  # 4 planted + 1 Evans gambit game
    assert unc[0].opponent_san == "d5" and unc[0].games_count == 3


# --- Judged with Stockfish ------------------------------------------------------


@pytest.mark.usefixtures("require_engine")
def test_judged_deviations_white(db) -> None:
    from app.tools.repertoire import save_tree

    rep = save_tree(db, None, WHITE, "pgn")  # stored rows must reference a real repertoire
    devs, unc = analyze_repertoire(_games(), WHITE, repertoire_id=rep.id, depth=DEPTH)
    by = {d.played_san: d for d in devs}
    assert by["Nxe5"].classification == "mistake" and by["Nxe5"].games_count == 3
    assert by["e5"].classification == "mistake" and by["e5"].games_count == 2
    # Every planted deviation found; nothing in book reported.
    assert {"Bc4", "Nxe5", "e5"} <= set(by)
    assert "Bb5" not in by and "Ba4" not in by
    # Store and load back in the same order.
    store_results(db, rep.id, devs, unc)
    loaded = load_deviations(db, rep.id, "white")
    assert [d.played_san for d in loaded] == [d.played_san for d in devs]


@pytest.mark.usefixtures("require_engine")
def test_gambit_repertoire_does_not_flag_its_own_sacrifice() -> None:
    kg = import_pgn('[Event "KG"]\n\n1. e4 e5 2. f4 exf4 3. Nf3 g5 4. h4 *', "white", "King's Gambit")
    games = [_g("e4 e5 f4 exf4 Nf3 g5 Bc4 g4 O-O", "white", "a"),
             _g("e4 e5 f4 exf4 Nf3 g5 h4 g4 Ne5", "white", "b")]
    devs, _ = analyze_repertoire(games, kg, depth=DEPTH, intentional_gambit=True)
    # 4.Bc4 (Muzio theory) deviates from the repertoire's 4.h4 but keeps the gambit.
    assert len(devs) == 1 and devs[0].played_san == "Bc4"
    assert devs[0].classification != "mistake"
    assert devs[0].is_gambit
