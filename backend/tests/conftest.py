"""Shared pytest fixtures.

Every test gets an isolated in-memory SQLite database so tests never touch the
developer's real ``repertoire.db``.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import create_engine

# Tests always run offline against fixtures and without the LLM.
os.environ.setdefault("OFFLINE", "1")
os.environ["ANTHROPIC_API_KEY"] = ""
# Never call a real provider from tests, even when .env holds a Groq key.
os.environ["LLM_API_KEY"] = ""
os.environ["LLM_PROVIDER"] = "groq"
# The global session (used by the run log and the API) points at a throwaway file.
import tempfile  # noqa: E402

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(prefix="repai-"), "test.db").replace("\\", "/")

from app.db import Base  # noqa: E402
from app.config import get_settings  # noqa: E402


@pytest.fixture()
def db() -> Iterator[Session]:
    """Fresh in-memory database with every table created."""
    from app import models  # noqa: F401

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def _close_engine_after_session() -> Iterator[None]:
    """Quit the batch Stockfish process when the test session ends."""
    yield
    from app.tools import engine

    engine.shutdown()


@pytest.fixture(scope="session")
def stockfish_available() -> bool:
    return get_settings().stockfish_abspath.exists()


@pytest.fixture()
def require_engine(stockfish_available: bool) -> None:
    if not stockfish_available:
        pytest.skip("Stockfish binary not found (set STOCKFISH_PATH)")
