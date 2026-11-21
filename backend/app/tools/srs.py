"""SM-2 spaced repetition (spec 8.5, Phase 16).

Grades are 0-5. First successful interval 1 day, second 6 days, then the
previous interval multiplied by the ease factor. A grade below 3 resets the
repetition count (the card is relearned from a 1-day interval).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Quiz, Review

MIN_EASE = 1.3


@dataclass
class SM2State:
    ease: float = 2.5
    interval_days: int = 0
    repetitions: int = 0


def sm2(state: SM2State, grade: int) -> SM2State:
    """Pure SM-2 update."""
    if not 0 <= grade <= 5:
        raise ValueError("grade must be 0..5")
    ease = max(MIN_EASE, state.ease + (0.1 - (5 - grade) * (0.08 + (5 - grade) * 0.02)))
    if grade < 3:
        return SM2State(ease=ease, interval_days=1, repetitions=0)
    reps = state.repetitions + 1
    if reps == 1:
        interval = 1
    elif reps == 2:
        interval = 6
    else:
        interval = round(state.interval_days * state.ease)
    return SM2State(ease=ease, interval_days=interval, repetitions=reps)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def schedule(session: Session, quiz_id: int, user_id: int, due_at: datetime | None = None) -> Review:
    """Create the review row for (quiz, user) if missing — idempotent."""
    row = session.scalars(select(Review).where(Review.quiz_id == quiz_id, Review.user_id == user_id)).first()
    if row is None:
        row = Review(quiz_id=quiz_id, user_id=user_id, due_at=due_at or datetime.now(timezone.utc))
        session.add(row)
        session.commit()
    return row


def grade_review(session: Session, quiz_id: int, user_id: int, grade: int, now: datetime | None = None) -> Review:
    now = now or datetime.now(timezone.utc)
    row = schedule(session, quiz_id, user_id, now)
    new = sm2(SM2State(row.ease, row.interval_days, row.repetitions), grade)
    row.ease, row.interval_days, row.repetitions = new.ease, new.interval_days, new.repetitions
    row.due_at = now + timedelta(days=new.interval_days)
    row.last_result = grade
    session.commit()
    return row


def get_due(session: Session, user_id: int, limit: int = 10, now: datetime | None = None) -> list[Quiz]:
    now = now or datetime.now(timezone.utc)
    rows = session.scalars(select(Review).where(Review.user_id == user_id).order_by(Review.due_at)).all()
    due = [r for r in rows if _aware(r.due_at) <= now][:limit]
    return [session.get(Quiz, r.quiz_id) for r in due]
