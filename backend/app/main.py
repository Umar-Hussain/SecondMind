"""FastAPI entry point for RepertoireAI.

Run from the ``backend`` folder with::

    uvicorn app.main:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="RepertoireAI",
    description="Personalized opening-repertoire and preparation agent for club chess players.",
    version="0.1.0",
)

# The React dev server runs on a different port, so allow it during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe used by the frontend and deployment checks."""
    return {"status": "ok"}
