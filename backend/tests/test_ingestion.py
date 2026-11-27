"""Lichess + Chess.com ingestion against saved fixtures."""

import pytest

from app.models import User
from app.tools import chesscom, lichess
from app.tools.games import fetch_user_games, merge_games, store_games
from app.tools.http import NotFoundError


def test_lichess_fetch_and_normalize() -> None:
    games = lichess.fetch_games("demo_player")
    assert games, "fixture should contain games"
    g = games[0]
    assert g.source == "lichess"
    assert g.color in ("white", "black")
    assert g.moves_uci[0] in ("e2e4", "d2d4")
    assert g.clocks and len(g.clocks) == len(g.moves_uci)
    # Newest first
    stamps = [x.played_at for x in games]
    assert stamps == sorted(stamps, reverse=True)


def test_lichess_max_games_respected() -> None:
    assert len(lichess.fetch_games("demo_player", max_games=5)) == 5


def test_chesscom_month_archive() -> None:
    games = chesscom.fetch_games("demo_player_cc")
    assert games
    assert all(g.source == "chesscom" for g in games)
    # [%clk] comments are parsed into clocks
    assert games[0].clocks is not None
    assert games[0].external_id.isdigit()


def test_chesscom_unknown_user_404() -> None:
    with pytest.raises(NotFoundError):
        chesscom.fetch_games("ghost_user")


def test_chesscom_empty_archive() -> None:
    assert chesscom.fetch_games("empty_user") == []


def test_merge_removes_cross_platform_duplicate() -> None:
    li = lichess.fetch_games("demo_player")
    cc = chesscom.fetch_games("demo_player_cc")
    merged = merge_games(li, cc)
    assert len(merged) == len(li) + len(cc) - 1  # exactly one planted duplicate
    keys = {(g.source, g.external_id) for g in merged}
    assert len(keys) == len(merged)


def test_merge_same_list_twice_is_idempotent() -> None:
    li = lichess.fetch_games("demo_player")
    assert len(merge_games(li, li)) == len(li)


def test_fetch_and_store_user_games(db) -> None:
    user = User(lichess_username="demo_player", chesscom_username="demo_player_cc")
    db.add(user)
    db.commit()
    games, warnings = fetch_user_games(user)
    assert not warnings
    added = store_games(db, user.id, games)
    assert added == len(games)
    # Storing again adds nothing.
    assert store_games(db, user.id, games) == 0


def test_two_users_can_store_the_same_game(db) -> None:
    games, _ = fetch_user_games(User(lichess_username="demo_player"))
    for name in ("a", "b"):
        u = User(lichess_username=name)
        db.add(u)
        db.commit()
        assert store_games(db, u.id, games[:3]) == 3
