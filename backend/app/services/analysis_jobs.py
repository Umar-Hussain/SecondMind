"""Game fetching and analysis as a background job, one per user.

``POST /analyze/start`` starts a thread and returns at once, so the user can keep using
the app while games download and Stockfish checks them. ``GET /analyze/status`` reports
the live stage and counts (the front end polls it and shows a progress bar on every page).
A finished or failed job stays readable until the next one starts.

Jobs live in this process's memory: on a restart the status is simply gone and the
user starts again. That is enough for a single free-tier web instance.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict, dataclass, field

from app.db import SessionLocal
from app.services import pipeline

log = logging.getLogger(__name__)

# What the user sees for each pipeline stage.
STAGE_TEXT = {
    "queued": "Starting…",
    "download": "Downloading your games",
    "games": "Checking your games with Stockfish",
    "moves": "Finding the best moves for your weak spots",
    "repertoires": "Comparing your games with your repertoires",
    "done": "Done",
    "error": "Something went wrong",
}
# Rough share of the whole job per stage, for one overall percentage.
_WEIGHT = {"download": (0, 10), "games": (10, 70), "moves": (70, 85), "repertoires": (85, 100)}


@dataclass
class Job:
    user_id: int
    state: str = "running"  # running | done | error
    stage: str = "queued"
    done: int = 0
    total: int = 0
    percent: int = 0
    message: str = STAGE_TEXT["queued"]
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    summary: dict | None = None
    error: str | None = None


_jobs: dict[int, Job] = {}
_lock = threading.Lock()


def status(user_id: int) -> dict | None:
    with _lock:
        job = _jobs.get(user_id)
        return asdict(job) if job else None


def start(user_id: int, max_games: int = 200, depth: int | None = None) -> dict:
    """Start a job for this user, or return the one already running."""
    with _lock:
        job = _jobs.get(user_id)
        if job and job.state == "running":
            return asdict(job)
        job = _jobs[user_id] = Job(user_id=user_id)
        snapshot = asdict(job)  # before the thread runs, so the caller always sees "running"
    threading.Thread(target=_run, args=(job, max_games, depth), daemon=True, name=f"analyze-{user_id}").start()
    return snapshot


def _progress(job: Job):
    def report(stage: str, done: int, total: int) -> None:
        lo, hi = _WEIGHT.get(stage, (0, 100))
        frac = done / total if total else 0
        with _lock:
            job.stage, job.done, job.total = stage, done, total
            job.percent = int(lo + (hi - lo) * frac)
            count = f" ({done} of {total})" if total > 1 else ""
            job.message = STAGE_TEXT.get(stage, stage) + count
    return report


def _run(job: Job, max_games: int, depth: int | None) -> None:
    try:
        with SessionLocal() as session:
            summary = pipeline.run_analysis(session, job.user_id, max_games=max_games, depth=depth,
                                            progress=_progress(job))
        with _lock:
            job.state, job.stage, job.percent, job.summary = "done", "done", 100, summary.__dict__
            job.message = f"Done: {summary.games_fetched} games checked"
    except Exception as exc:  # noqa: BLE001 - the user gets a readable message, the log the trace
        log.exception("analysis job failed for user %s", job.user_id)
        with _lock:
            job.state, job.stage, job.error = "error", "error", str(exc) or exc.__class__.__name__
            job.message = STAGE_TEXT["error"]
    finally:
        job.finished_at = time.time()
