"""Chess.com Published-Data API client (spec Phase 3).

Flow::

    GET https://api.chess.com/pub/player/{username}/games/archives
    -> list of monthly archive URLs
    GET each monthly archive, newest first, ONE AT A TIME

Chess.com asks automated clients to send a descriptive User-Agent with a
contact address and to never parallelise requests, so archives are fetched
serially with a delay between them. Past months never change, so they are
cached on disk; the current month is always refetched.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from app.config import DATA_DIR, get_settings
from app.schemas import NormalizedGame
from app.tools.http import NotFoundError, fixture_path, get_text
from app.tools.pgn_utils import mainline_uci_and_clocks, player_result, read_pgn_games

API = "https://api.chess.com/pub"
CACHE_DIR = DATA_DIR / "cache" / "chesscom"


def _headers() -> dict[str, str]:
    contact = get_settings().chesscom_contact_email or "no-contact-configured"
    return {"User-Agent": f"SecondMind/0.1 (chess opening trainer; contact: {contact})"}


def _archive_fixture(username: str, url: str):
    year, month = url.rstrip("/").split("/")[-2:]
    return fixture_path("chesscom", f"{username}_{year}_{month}.json")


def _get_archive(username: str, url: str) -> dict:
    """Fetch one monthly archive, using the on-disk cache for past months."""
    year, month = (int(x) for x in url.rstrip("/").split("/")[-2:])
    now = datetime.now(timezone.utc)
    is_current = (year, month) == (now.year, now.month)
    cache_file = CACHE_DIR / username.lower() / f"{year}_{month:02d}.json"
    if not get_settings().offline and not is_current and cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))

    body = get_text(url, headers=_headers(), fixture=_archive_fixture(username, url), min_interval=1.5)
    data = json.loads(body)
    if not get_settings().offline and not is_current:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(body, encoding="utf-8")
    return data


def normalize_game(raw: dict, username: str) -> NormalizedGame | None:
    """Turn one Chess.com archive entry into a ``NormalizedGame``."""
    if raw.get("rules", "chess") != "chess" or not raw.get("pgn"):
        return None
    me = username.lower()
    white = raw.get("white", {})
    black = raw.get("black", {})
    if white.get("username", "").lower() == me:
        color, opp = "white", black
    elif black.get("username", "").lower() == me:
        color, opp = "black", white
    else:
        return None

    games = read_pgn_games(raw["pgn"])
    if not games:
        return None
    pgn_game = games[0]
    moves, clocks = mainline_uci_and_clocks(pgn_game)
    if not moves:
        return None
    result = player_result(pgn_game.headers.get("Result", "*"), color)
    url = raw.get("url", "")
    end_time = raw.get("end_time")

    return NormalizedGame(
        source="chesscom",
        # The numeric id at the end of the game URL is stable and unique.
        external_id=url.rstrip("/").split("/")[-1] if url else pgn_game.headers.get("Link", ""),
        pgn=raw["pgn"],
        color=color,
        result=result,
        opponent=opp.get("username", "unknown"),
        opponent_rating=opp.get("rating"),
        time_control=f"{raw.get('time_control', '')} ({raw.get('time_class', '')})",
        played_at=datetime.fromtimestamp(end_time, tz=timezone.utc) if end_time else None,
        moves_uci=moves,
        clocks=clocks,
        url=url or None,
        white=white.get("username", ""),
        black=black.get("username", ""),
    )


def fetch_games(username: str, max_games: int = 200, since: datetime | None = None) -> list[NormalizedGame]:
    """Collect up to ``max_games`` rated standard games, newest first.

    Raises ``NotFoundError`` for unknown users (HTTP 404). An account with no
    games returns an empty list.
    """
    body = get_text(
        f"{API}/player/{username.lower()}/games/archives",
        headers=_headers(),
        fixture=fixture_path("chesscom", f"archives_{username}.json"),
    )
    archives: list[str] = json.loads(body).get("archives", [])
    collected: list[NormalizedGame] = []
    for url in reversed(archives):  # newest month first
        month_games = _get_archive(username, url).get("games", [])
        # Within a month the API returns oldest first; reverse for newest first.
        for raw in sorted(month_games, key=lambda g: g.get("end_time", 0), reverse=True):
            if not raw.get("rated", False):
                continue
            game = normalize_game(raw, username)
            if game is None:
                continue
            if since and game.played_at and game.played_at < since:
                return collected
            collected.append(game)
            if len(collected) >= max_games:
                return collected
    return collected


def fetch_profile(username: str) -> dict:
    if get_settings().offline:
        return {"username": username, "source": "chesscom"}
    return json.loads(get_text(f"{API}/player/{username.lower()}", headers=_headers()))


__all__ = ["fetch_games", "fetch_profile", "normalize_game", "NotFoundError"]
