"""Delivery: calendar (.ics) reminders (spec 11.4, Phase 17).

The web app is the only delivery channel; the scheduled jobs prepare
briefings and due quizzes, and these calendar events remind the player to
open them. Every event links back to already-verified content in the app.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ics import Calendar, Event

WEB_BASE = "http://localhost:5173"


def briefing_ics(opponent: str, briefing_id: int, game_time: datetime, lead_minutes: int = 60) -> str:
    """One event for the briefing (an hour before the game) and one for the game."""
    if game_time.tzinfo is None:
        game_time = game_time.replace(tzinfo=timezone.utc)
    cal = Calendar()
    prep = Event(name=f"Prep vs {opponent} (SecondMind briefing)", begin=game_time - timedelta(minutes=lead_minutes),
                 duration=timedelta(minutes=30),
                 description=f"Open your briefing: {WEB_BASE}/scout?briefing={briefing_id}")
    prep.url = f"{WEB_BASE}/scout?briefing={briefing_id}"
    game = Event(name=f"Game vs {opponent}", begin=game_time, duration=timedelta(hours=1))
    cal.events.add(prep)
    cal.events.add(game)
    return cal.serialize()


def review_session_ics(user_id: int, when: datetime, quizzes_due: int) -> str:
    """A short spaced-repetition review session in the player's calendar."""
    cal = Calendar()
    cal.events.add(Event(name=f"SecondMind review ({quizzes_due} quizzes)", begin=when,
                         duration=timedelta(minutes=15), description=f"{WEB_BASE}/train?user={user_id}"))
    return cal.serialize()
