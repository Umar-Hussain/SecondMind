"""Lichess API client (spec Phase 3).

Uses the public games export endpoint, streamed as NDJSON::

    GET https://lichess.org/api/games/user/{username}
    Accept: application/x-ndjson

No password is ever requested. An optional personal token (``LICHESS_TOKEN``)
raises the rate limit. Every response can be recorded to / replayed from
``backend/data/fixtures/lichess`` so the project runs offline.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from app.config import get_settings
from app.schemas import NormalizedGame
from app.tools.http import fixture_path, get_text
from app.tools.pgn_utils import read_pgn_games, san_line_to_uci

API = "https://lichess.org"


def _headers(accept: str = "application/x-ndjson") -> dict[str, str]:
    headers = {"Accept": accept, "User-Agent": "SecondMind (student project)"}
    token = get_settings().lichess_token
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def normalize_game(raw: dict, username: str) -> NormalizedGame | None:
    """Turn one Lichess NDJSON record into a ``NormalizedGame``.

    Returns ``None`` for games that cannot be analysed (variants, games the
    user did not play, or no moves).
    """
    if raw.get("variant", "standard") != "standard" or not raw.get("moves"):
        return None
    players = raw.get("players", {})
    white = players.get("white", {}).get("user", {}).get("name", "")
    black = players.get("black", {}).get("user", {}).get("name", "")
    me = username.lower()
    if white.lower() == me:
        color, opp_side = "white", "black"
    elif black.lower() == me:
        color, opp_side = "black", "white"
    else:
        return None

    winner = raw.get("winner")
    if winner is None:
        result = "draw"
    else:
        result = "win" if winner == color else "loss"

    moves_uci = san_line_to_uci(raw["moves"])
    # Lichess clocks are centiseconds remaining after each ply.
    clocks = [c / 100 for c in raw["clocks"]] if raw.get("clocks") else None
    clock = raw.get("clock") or {}
    tc = f"{clock.get('initial', 0)}+{clock.get('increment', 0)}" if clock else raw.get("speed")
    created = raw.get("createdAt")
    opp = players.get(opp_side, {})

    return NormalizedGame(
        source="lichess",
        external_id=raw["id"],
        pgn=raw.get("pgn") or raw["moves"],
        color=color,
        result=result,
        opponent=opp.get("user", {}).get("name", "anonymous"),
        opponent_rating=opp.get("rating"),
        time_control=tc,
        played_at=datetime.fromtimestamp(created / 1000, tz=timezone.utc) if created else None,
        moves_uci=moves_uci,
        clocks=clocks,
        url=f"{API}/{raw['id']}",
        white=white,
        black=black,
    )


def fetch_games(
    username: str,
    max_games: int = 200,
    since: datetime | None = None,
    rated_only: bool = True,
) -> list[NormalizedGame]:
    """Fetch and normalize a user's most recent games (newest first)."""
    params: dict[str, str | int] = {
        "max": max_games,
        "pgnInJson": "true",
        "opening": "true",
        "moves": "true",
        "clocks": "true",
        "evals": "false",
    }
    if rated_only:
        params["rated"] = "true"
    if since:
        params["since"] = int(since.timestamp() * 1000)

    body = get_text(
        f"{API}/api/games/user/{username}",
        headers=_headers(),
        params=params,
        fixture=fixture_path("lichess", f"games_{username}.ndjson"),
    )
    games: list[NormalizedGame] = []
    for line in body.splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        if rated_only and not raw.get("rated", True):
            continue
        game = normalize_game(raw, username)
        if game:
            games.append(game)
        if len(games) >= max_games:
            break
    return games


def fetch_profile(username: str) -> dict:
    """Public profile (ratings). Offline mode returns a minimal stub."""
    if get_settings().offline:
        return {"username": username, "source": "lichess"}
    body = get_text(f"{API}/api/user/{username}", headers=_headers("application/json"))
    return json.loads(body)


def export_study_pgn(study_url: str) -> str:
    """Export every chapter of a Lichess study as PGN (for repertoire import)."""
    study_id = study_url.rstrip("/").split("/study/")[-1].split("/")[0]
    return get_text(
        f"{API}/api/study/{study_id}.pgn",
        headers=_headers("application/x-chess-pgn"),
        params={"comments": "true", "variations": "true"},
        fixture=fixture_path("lichess", f"study_{study_id}.pgn"),
    )


def pgn_to_ucis(pgn: str) -> list[str]:
    """Convenience: main line of the first game in a PGN string as UCI."""
    games = read_pgn_games(pgn)
    if not games:
        return []
    return [move.uci() for move in games[0].mainline_moves()]


__all__ = ["fetch_games", "fetch_profile", "export_study_pgn", "normalize_game", "pgn_to_ucis"]
