"""FastAPI entry point for RepertoireAI.

Run from the ``backend`` folder with::

    uvicorn app.main:app --reload
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import routes, ws
from app.db import init_db
from app.tools import engine


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()  # tables are created on startup (spec Phase 2)
    yield
    engine.shutdown()  # never leave a Stockfish process behind


app = FastAPI(
    title="RepertoireAI",
    description="Personalized opening-repertoire and preparation agent for club chess players.",
    version="0.1.0",
    lifespan=lifespan,
)

# The React dev server runs on a different port, so allow it during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes.router)
app.include_router(ws.router)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe used by the frontend and deployment checks."""
    return {"status": "ok"}
