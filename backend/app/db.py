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


def normalize_url(url: str) -> str:
    """Hosted Postgres (Neon, Render, Heroku) hands out ``postgres://`` / ``postgresql://``
    URLs; SQLAlchemy needs the driver named explicitly: ``postgresql+psycopg://``."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def enforce_sqlite_foreign_keys(eng: Engine) -> None:
    """SQLite ignores foreign keys unless asked; enforce them so SQLite behaves like Postgres."""
    from sqlalchemy import event

    @event.listens_for(eng, "connect")
    def _fk_on(dbapi_conn, _record) -> None:  # pragma: no cover - trivial
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


def make_engine(url: str | None = None) -> Engine:
    """Create an engine: SQLite locally, Postgres (e.g. Neon) when DATABASE_URL points there."""
    url = normalize_url(url or get_settings().database_url)
    if url.startswith("sqlite"):
        # FastAPI serves requests from several threads.
        eng = create_engine(url, connect_args={"check_same_thread": False}, future=True)
        enforce_sqlite_foreign_keys(eng)
        return eng
    # Serverless Postgres closes idle connections: test each one before use and recycle often.
    # connect_timeout matters: a hostname with several addresses can have one that never
    # answers; without a timeout the driver waits on it forever instead of trying the next.
    return create_engine(url, future=True, pool_pre_ping=True, pool_recycle=300, pool_size=5, max_overflow=5,
                         connect_args={"connect_timeout": 10})


engine: Engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db(bind: Engine | None = None) -> None:
    """Create every table. Importing models registers them on ``Base``."""
    from app import models  # noqa: F401  (import for side effect)

    target = bind or engine
    Base.metadata.create_all(bind=target)
    _add_missing_columns(target)
    _fix_game_uniqueness(target)


def _fix_game_uniqueness(bind: Engine) -> None:
    """Replace the old ``UNIQUE (source, external_id)`` rule on ``games`` with the per-user rule.

    Databases created before games were stored per user still say a game may exist only once
    in the whole table, so a second user fetching the same public game crashed the analysis.
    Postgres can drop the constraint in place; SQLite cannot, so the table is rebuilt with
    the documented create-copy-drop-rename procedure.
    """
    from sqlalchemy import inspect, text
    from sqlalchemy.schema import CreateTable

    insp = inspect(bind)
    if not insp.has_table("games"):
        return
    old = [u for u in insp.get_unique_constraints("games") if sorted(u["column_names"]) == ["external_id", "source"]]
    if not old:
        return
    table = Base.metadata.tables["games"]
    cols = ", ".join(f'"{c.name}"' for c in table.columns)
    with bind.begin() as conn:
        if bind.dialect.name == "sqlite":
            ddl = str(CreateTable(table).compile(dialect=bind.dialect)).replace("CREATE TABLE games", "CREATE TABLE games_new", 1)
            conn.execute(text(ddl))
            conn.execute(text(f"INSERT INTO games_new ({cols}) SELECT {cols} FROM games"))
            conn.execute(text("DROP TABLE games"))
            conn.execute(text("ALTER TABLE games_new RENAME TO games"))
        else:
            for u in old:
                conn.execute(text(f'ALTER TABLE games DROP CONSTRAINT "{u["name"]}"'))
            conn.execute(text("ALTER TABLE games ADD CONSTRAINT uq_game_user_source_ext UNIQUE (user_id, source, external_id)"))


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
                    if isinstance(value, bool):
                        literal = ("1" if value else "0") if bind.dialect.name == "sqlite" else ("TRUE" if value else "FALSE")
                    else:
                        literal = repr(value)
                    default = f" DEFAULT {literal}"
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
