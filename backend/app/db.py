"""Database engine and session management (SQLAlchemy 2.0 style).

SQLite is the default so the whole project runs from a clean clone; the URL
can be switched to Postgres via ``DATABASE_URL`` without code changes.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """Declarative base shared by every table in ``app.models``."""


def make_engine(url: str | None = None) -> Engine:
    """Create an engine. SQLite needs ``check_same_thread=False`` for FastAPI."""
    url = url or get_settings().database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args, future=True)


engine: Engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db(bind: Engine | None = None) -> None:
    """Create every table. Importing models registers them on ``Base``."""
    from app import models  # noqa: F401  (import for side effect)

    Base.metadata.create_all(bind=bind or engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for scripts and jobs: commit on success, rollback on error."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency that yields one session per request."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
