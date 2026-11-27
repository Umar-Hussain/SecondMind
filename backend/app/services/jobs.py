"""Scheduled automation.

* daily   — re-fetch new games, re-mine leaks, refresh deviation statuses;
* daily   — create quizzes for new leaks and queue the due ones for delivery;
* one-off — generate and deliver a briefing one hour before a scheduled game.

Every job is idempotent (quizzes are keyed by (FEN, answer), reviews by
(quiz, user), games by (source, id)) and logged to the ``runs`` table.

Run the scheduler as its own process::

    python -m app.services.jobs
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.models import User
from app.runlog import timed
from app.services import pipeline
from app.tools import quiz, srs


def refresh_user(user_id: int, depth: int | None = None) -> dict:
    """Re-fetch and re-mine one user (new games only are inserted)."""
    with timed("job", "refresh_user", {"user_id": user_id}) as out, SessionLocal() as s:
        summary = pipeline.run_analysis(s, user_id, depth=depth)
        out["output"] = summary.__dict__
        return summary.__dict__


def training_for_user(user_id: int, depth: int | None = None) -> dict:
    """Create quizzes from open leaks and schedule them; return what is due now."""
    with timed("job", "training_for_user", {"user_id": user_id}) as out, SessionLocal() as s:
        made, rejected = quiz.quizzes_from_leaks(s, user_id, depth=depth)
        for q in made:
            srs.schedule(s, q.id, user_id)
        due = srs.get_due(s, user_id, limit=10)
        result = {"quizzes": len(made), "rejected": len(rejected), "due": [q.id for q in due]}
        out["output"] = result
        return result


def pregame_briefing(user_id: int, opponent: str, platform: str = "lichess", depth: int | None = None) -> int:
    from app.services.briefing import prepare

    with timed("job", "pregame_briefing", {"user_id": user_id, "opponent": opponent}) as out, SessionLocal() as s:
        _, bid = prepare(s, user_id, opponent, platform, depth=depth)
        out["output"] = {"briefing_id": bid}
        return bid


def daily_all_users() -> None:
    with SessionLocal() as s:
        ids = [u.id for u in s.scalars(select(User))]
    for uid in ids:
        refresh_user(uid)
        training_for_user(uid)


def build_scheduler():
    from apscheduler.schedulers.blocking import BlockingScheduler

    sched = BlockingScheduler(timezone="UTC")
    sched.add_job(daily_all_users, "cron", hour=6, minute=0, id="daily", replace_existing=True)
    return sched


def schedule_game(sched, user_id: int, opponent: str, game_time: datetime, platform: str = "lichess") -> None:
    """Briefing one hour before the game (replace_existing keeps it idempotent)."""
    run_at = game_time - timedelta(hours=1)
    if run_at < datetime.now(timezone.utc):
        run_at = datetime.now(timezone.utc) + timedelta(seconds=5)
    sched.add_job(pregame_briefing, "date", run_date=run_at, args=[user_id, opponent, platform],
                  id=f"brief-{user_id}-{opponent}-{game_time.isoformat()}", replace_existing=True)


if __name__ == "__main__":  # pragma: no cover
    init_db()
    build_scheduler().start()
