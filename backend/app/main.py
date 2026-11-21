"""FastAPI entry point for SecondMind (opening-repertoire agent).

Run from the ``backend`` folder with::

    uvicorn app.main:app --reload
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import routes, ws
from app.config import ROOT_DIR
from app.db import init_db
from app.tools import engine

logger = logging.getLogger("secondmind")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()  # tables are created (and new columns added) on startup
    from app.auth import ensure_admin
    from app.db import SessionLocal

    with SessionLocal() as session:
        ensure_admin(session)  # admin from ADMIN_USERNAME / ADMIN_PASSWORD, if set
    yield
    engine.shutdown()  # never leave a Stockfish process behind


app = FastAPI(
    title="SecondMind",
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
# The same routes under /api: in production the built web app calls /api/... on
# this server, exactly like the Vite dev proxy does during development.
app.include_router(routes.router, prefix="/api", include_in_schema=False)
app.include_router(ws.router, prefix="/api")


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """Unexpected failures: full traceback to the server log, a short JSON message to the client."""
    error_id = uuid.uuid4().hex[:8]
    logger.exception("unhandled error %s on %s %s", error_id, request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": f"Server error (reference {error_id}). Please try again."})


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe used by the frontend and deployment checks."""
    return {"status": "ok"}


# --- Serve the built React app (single-container deployment, e.g. Hugging Face Spaces) ---
_DIST = ROOT_DIR / "frontend" / "dist"
if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")
    if (_DIST / "stockfish").exists():
        app.mount("/stockfish", StaticFiles(directory=_DIST / "stockfish"), name="stockfish")

    @app.get("/", include_in_schema=False)
    def spa_index() -> FileResponse:
        return FileResponse(_DIST / "index.html")
