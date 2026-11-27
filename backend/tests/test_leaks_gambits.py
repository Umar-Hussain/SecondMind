"""leak mining and gambit handling on the fixture games."""

import pytest

from app.tools import gambits, lichess, chesscom
from app.tools.games import merge_games
from app.tools.leaks import analyze_game, mine_leaks
from app.tools.pgn_utils import san_line_to_uci
from app.schemas import NormalizedGame

DEPTH = 12


def _game(moves: str, color: str, result: str = "win", gid: str = "t") -> NormalizedGame:
    return NormalizedGame(source="lichess", external_id=gid, pgn="", color=color, result=result,
                          opponent="x", moves_uci=san_line_to_uci(moves))


# --- Registry / detection (no engine needed) --------------------------------


def test_registry_loads_and_has_baselines() -> None:
    reg = gambits.registry()
    assert {"kings_gambit", "englund_gambit", "evans_gambit", "smith_morra", "danish_gambit"} <= set(reg)
    assert reg["englund_gambit"].objective_eval_cp is not None


@pytest.mark.parametrize("moves,color,gid,by_user", [
    ("e4 e5 f4 exf4 Nf3", "white", "kings_gambit", True),
    ("e4 e5 Nf3 Nc6 Bc4 Bc5 b4", "white", "evans_gambit", True),
    ("e4 c5 d4 cxd4 c3", "white", "smith_morra", True),
    ("e4 e5 d4 exd4 c3 dxc3", "white", "danish_gambit", True),
    ("d4 e5 dxe5 Nc6", "black", "englund_gambit", True),
    ("d4 e5 dxe5 Nc6", "white", "englund_gambit", False),
])
def test_detect_gambit(moves, color, gid, by_user) -> None:
    m = gambits.detect_gambit(san_line_to_uci(moves), color)
    assert m is not None and m.gambit.id == gid and m.played_by_user is by_user


def test_queens_gambit_is_not_a_gambit() -> None:
    assert gambits.detect_gambit(san_line_to_uci("d4 d5 c4 dxc4"), "white") is None


def test_plain_material_deficit_is_not_a_gambit() -> None:
    # White just hangs a pawn; no gambit theory matches.
    assert gambits.detect_gambit(san_line_to_uci("a3 e5 b4 Bxb4"), "white") is None


# --- Engine-backed tests ------------------------------------------------------


@pytest.mark.usefixtures("require_engine")
@pytest.mark.parametrize("moves,color", [
    ("e4 e5 f4 exf4 Nf3 g5 h4 g4 Ne5 Nf6 Bc4 d5 exd5 Bd6", "white"),
    ("e4 e5 Nf3 Nc6 Bc4 Bc5 b4 Bxb4 c3 Ba5 d4 exd4 O-O Nge7", "white"),
    ("e4 c5 d4 cxd4 c3 dxc3 Nxc3 Nc6 Nf3 d6 Bc4 e6 O-O Nf6", "white"),
    ("e4 e5 d4 exd4 c3 dxc3 Bc4 cxb2 Bxb2 d5 Bxd5 Nf6", "white"),
    ("d4 e5 dxe5 Nc6 Nf3 Qe7 Bf4 Qb4+ Bd2 Qxb2 Nc3 Bb4", "black"),
])
def test_correct_gambit_play_has_zero_flags(moves, color) -> None:
    assert analyze_game(_game(moves, color), depth=DEPTH) == []


@pytest.mark.usefixtures("require_engine")
def test_kings_gambit_deviation_is_flagged() -> None:
    findings = analyze_game(_game("e4 e5 f4 exf4 Nf3 g5 Bc4 g4 Qe2 gxf3 Qxf3 Qh4+", "white"), depth=DEPTH)
    assert [f.kind for f in findings] == ["gambit_deviation"]
    assert findings[0].played == "d1e2"


@pytest.mark.usefixtures("require_engine")
def test_englund_defender_trap_is_flagged() -> None:
    findings = analyze_game(_game("d4 e5 dxe5 Nc6 Nf3 Qe7 Bf4 Qb4+ Bd2 Qxb2 Bc3 Bb4", "white"), depth=DEPTH)
    assert findings and findings[0].kind == "defender_trap"
    assert findings[0].played == "d2c3"


@pytest.mark.usefixtures("require_engine")
def test_mine_fixture_leaks() -> None:
    games = merge_games(lichess.fetch_games("demo_player"), chesscom.fetch_games("demo_player_cc"))
    leaks = mine_leaks(games, depth=DEPTH)
    by_move = {(lk.played, lk.kind): lk for lk in leaks}

    # Planted blunder 4.Nxe5?? appears once with frequency 3.
    blunder = by_move[("f3e5", "mistake")]
    assert blunder.frequency == 3 and blunder.avg_loss > 80

    # Ranking: frequency x avg loss, descending.
    real = [lk for lk in leaks if lk.kind != "gambit_note"]
    assert [lk.score for lk in real] == sorted((lk.score for lk in real), reverse=True)

    # No gambit sacrifice is ever flagged as a mistake.
    sacrifices = {"f2f4", "b2b4", "c2c3", "e7e5"}
    assert not [lk for lk in leaks if lk.kind == "mistake" and lk.played in sacrifices and lk.ply <= 7]

    # Dubious gambit the player chose -> informational note only.
    notes = [lk for lk in leaks if lk.kind == "gambit_note"]
    assert any(n.gambit_id == "englund_gambit" for n in notes)
