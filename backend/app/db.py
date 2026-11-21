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

    target = bind or engine
    Base.metadata.create_all(bind=target)
    _add_missing_columns(target)


def _add_missing_columns(bind: Engine) -> None:
    """Tiny additive migration: add columns introduced after a database was created.

    ``create_all`` never alters existing tables, so an older ``repertoire.db`` would
    miss new columns. Only *adding* nullable columns is supported, which is all this
    project needs; constraints on new columns are not retrofitted.
    """
    from sqlalchemy import inspect, text

    insp = inspect(bind)
    with bind.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                ddl_type = col.type.compile(dialect=bind.dialect)
                default = ""
                if col.default is not None and getattr(col.default, "is_scalar", False):
                    value = col.default.arg
                    default = f" DEFAULT {int(value) if isinstance(value, bool) else repr(value)}"
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{col.name}" {ddl_type}{default}'))


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
