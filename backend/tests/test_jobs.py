"""Phase 18: running a job twice does not duplicate games, quizzes or reviews."""

import pytest
from sqlalchemy import func, select

from app.db import SessionLocal, init_db
from app.models import Game, Quiz, Review, User
from app.services import jobs

pytestmark = pytest.mark.usefixtures("require_engine")


def _count(model) -> int:
    with SessionLocal() as s:
        return s.scalar(select(func.count()).select_from(model))


def test_jobs_are_idempotent() -> None:
    init_db()
    with SessionLocal() as s:
        u = User(lichess_username="demo_player", chesscom_username="demo_player_cc")
        s.add(u)
        s.commit()
        uid = u.id

    jobs.refresh_user(uid, depth=10)
    first = jobs.training_for_user(uid, depth=10)
    counts = (_count(Game), _count(Quiz), _count(Review))

    jobs.refresh_user(uid, depth=10)
    second = jobs.training_for_user(uid, depth=10)
    assert (_count(Game), _count(Quiz), _count(Review)) == counts
    assert first["quizzes"] >= 1 and second["due"] == first["due"]
