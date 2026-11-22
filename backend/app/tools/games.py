"""Merge games from both platforms and store them (spec 5.1, Phase 3 step 4).

Duplicates are removed by:

1. the same ``(source, external_id)`` pair, and
2. the same players, the same day and the same move list — this catches a game
   that exists on both platforms (for example an imported OTB game).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Game, User
from app.schemas import NormalizedGame
from app.tools import chesscom, lichess
from app.tools.http import NotFoundError


def _content_key(g: NormalizedGame) -> tuple:
    """Platform-independent identity: players (by color), day, and moves."""
    day = g.played_at.date().isoformat() if g.played_at else ""
    # Usernames differ across platforms, so compare the opponent plus color.
    return (g.color, g.opponent.lower(), day, tuple(g.moves_uci))


def merge_games(*sources: Iterable[NormalizedGame]) -> list[NormalizedGame]:
    """Combine game lists, dropping duplicates. Order: newest first."""
    seen_ids: set[tuple[str, str]] = set()
    seen_content: set[tuple] = set()
    merged: list[NormalizedGame] = []
    for games in sources:
        for g in games:
            id_key = (g.source, g.external_id)
            content = _content_key(g)
            if id_key in seen_ids or content in seen_content:
                continue
            seen_ids.add(id_key)
            seen_content.add(content)
            merged.append(g)
    merged.sort(key=lambda g: g.played_at.timestamp() if g.played_at else 0, reverse=True)
    return merged


def fetch_user_games(user: User, max_games: int = 200, since: dict | None = None
                     ) -> tuple[list[NormalizedGame], list[str]]:
    """Fetch from every linked platform. Returns (games, warnings).

    ``since`` maps a source ("lichess" / "chesscom") to the newest stored game's time, so a
    re-fetch only downloads newer games."""
    since = since or {}
    warnings: list[str] = []
    per_source: list[list[NormalizedGame]] = []
    if user.lichess_username:
        try:
            per_source.append(lichess.fetch_games(user.lichess_username, max_games=max_games,
                                                  since=_after(since.get("lichess"))))
        except NotFoundError:
            warnings.append(f"Lichess user '{user.lichess_username}' not found")
    if user.chesscom_username:
        try:
            per_source.append(chesscom.fetch_games(user.chesscom_username, max_games=max_games,
                                                   since=_after(since.get("chesscom"))))
        except NotFoundError:
            warnings.append(f"Chess.com user '{user.chesscom_username}' not found")
    merged = merge_games(*per_source)[:max_games]
    return merged, warnings


def _after(ts):
    """A stored timestamp as an aware datetime one second later (so the newest game is not refetched)."""
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts + timedelta(seconds=1)


def store_games(session: Session, user_id: int, games: Iterable[NormalizedGame]) -> int:
    """Insert games that are not stored yet. Returns the number of new rows."""
    existing = {
        (s, e) for s, e in session.execute(select(Game.source, Game.external_id).where(Game.user_id == user_id))
    }
    added = 0
    for g in games:
        if (g.source, g.external_id) in existing:
            continue
        session.add(
            Game(
                user_id=user_id,
                source=g.source,
                external_id=g.external_id,
                pgn=g.pgn,
                color=g.color,
                result=g.result,
                opponent=g.opponent,
                opponent_rating=g.opponent_rating,
                time_control=g.time_control,
                played_at=g.played_at,
                moves_uci=g.moves_uci,
                clocks=g.clocks,
                url=g.url,
            )
        )
        existing.add((g.source, g.external_id))
        added += 1
    session.commit()
    return added


def to_normalized(game: Game) -> NormalizedGame:
    """Convert a stored row back to the common schema."""
    return NormalizedGame(
        source=game.source,  # type: ignore[arg-type]
        external_id=game.external_id,
        pgn=game.pgn,
        color=game.color,  # type: ignore[arg-type]
        result=game.result,  # type: ignore[arg-type]
        opponent=game.opponent,
        opponent_rating=game.opponent_rating,
        time_control=game.time_control,
        played_at=game.played_at,
        moves_uci=list(game.moves_uci or []),
        clocks=game.clocks,
        url=game.url,
    )
