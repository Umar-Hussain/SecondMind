"""Opponent explorer: games for the board, engine-checked weak spots with paths, your repertoire moves."""

import itertools

import chess
import pytest
from fastapi.testclient import TestClient

from app.config import FIXTURES_DIR
from app.main import app
from app.tools.scouting import speed_of

_ids = itertools.count(1)


@pytest.fixture(scope="module")
def api():
    with TestClient(app) as c:
        yield c


def _user(api) -> dict:
    res = api.post("/auth/signup", json={"username": f"scouter{next(_ids)}", "password": "scout-pass-123"}).json()
    return {"Authorization": f"Bearer {res['token']}"}


def test_speed_classes() -> None:
    assert [speed_of(x) for x in ("60+0", "180+2", "600+0", "600 (rapid)", "1800+20", "86400 (daily)")] == \
        ["bullet", "blitz", "rapid", "rapid", "classical", "classical"]


def test_scout_games_for_the_board(api) -> None:
    h = _user(api)
    res = api.get("/scout/games", headers=h, params={"opponent": "rival_player"}).json()
    assert res["count"] == 15
    g = res["games"][0]
    assert {"moves", "opp_color", "result", "speed", "url", "white", "black"} <= set(g)
    board = chess.Board()
    for u in g["moves"]:
        board.push_uci(u)  # moves replay legally from the start
    assert api.get("/scout/games", headers=h, params={"opponent": "x", "platform": "fide"}).status_code == 422
    assert api.get("/scout/games", params={"opponent": "rival_player"}).status_code == 401


@pytest.mark.usefixtures("require_engine")
def test_profile_weak_spots_have_board_paths(api) -> None:
    h = _user(api)
    prof = api.get("/scout/profile", headers=h, params={"opponent": "rival_player", "depth": 10}).json()
    assert prof["repeated_lines"]
    for w in prof["weaknesses"]:
        board = chess.Board()
        for u in w["path"]:
            board.push_uci(u)
        assert board.fen() == w["fen"]  # the path really reaches the position
        assert chess.Move.from_uci(w["move"]) in board.legal_moves
        if w["punish"]:
            board.push_uci(w["move"])
            assert chess.Move.from_uci(w["punish"]) in board.legal_moves


def test_repertoire_moves_in_a_position(api) -> None:
    h = _user(api)
    api.post("/repertoires", headers=h, json={"name": "e4", "color": "white",
                                              "pgn": (FIXTURES_DIR / "repertoire_white.pgn").read_text()})
    after_e5 = chess.Board()
    for san in ("e4", "e5", "Nf3", "Nc6"):
        after_e5.push_san(san)
    res = api.get("/repertoire-moves", headers=h, params={"fen": after_e5.fen()}).json()
    assert res["color"] == "white"
    assert [m["san"] for m in res["moves"]] == ["Bb5"] and res["moves"][0]["repertoire"] == "e4"
    # Black to move: no White repertoire move is offered.
    after_e5.push_san("Bb5")
    assert api.get("/repertoire-moves", headers=h, params={"fen": after_e5.fen()}).json()["moves"] == []
