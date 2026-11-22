"""Game fetching and analysis as a background job, one per user.

``POST /analyze/start`` starts a thread and returns at once, so the user can keep using
the app while games download and Stockfish checks them. ``GET /analyze/status`` reports
the live stage and counts (the front end polls it and shows a progress bar on every page).

One job prepares every page:

1. download new games, check them, compare them with the repertoires (Deviations);
2. build and save the gap report (Gap report opens instantly afterwards);
3. create quizzes from the costliest leaks and schedule them (Train).

``kind="report"`` runs only steps 2-3 (the "Rebuild" button on the Gap report).
A finished or failed job stays readable until the next one starts. Jobs live in this
process's memory: after a restart the status is simply gone and the user starts again,
which is enough for a single free-tier web instance.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict, dataclass, field

from sqlalchemy import select

from app.db import SessionLocal
from app.models import SavedReport, User
from app.services import pipeline, report
from app.tools import quiz, srs

log = logging.getLogger(__name__)

# What the user sees for each stage.
STAGE_TEXT = {
    "queued": "Starting…",
    "download": "Downloading your games",
    "games": "Checking your games with Stockfish",
    "moves": "Finding the best moves for your weak spots",
    "repertoires": "Comparing your games with your repertoires",
    "report": "Writing your gap report",
    "training": "Creating training quizzes",
    "done": "Done",
    "error": "Something went wrong",
}
# Share of the whole job per stage, for one overall percentage.
_WEIGHTS = {
    "full": {"download": (0, 8), "games": (8, 50), "moves": (50, 58), "repertoires": (58, 66),
             "report": (66, 92), "training": (92, 100)},
    "report": {"report": (0, 80), "training": (80, 100)},
}
REPORT_TOP = 8
LLM_BUDGET_S = 40.0  # per explanation in the background job; then the verified template is used
QUIZZES = 8


@dataclass
class Job:
    user_id: int
    kind: str = "full"
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


def start(user_id: int, max_games: int = 200, depth: int | None = None, kind: str = "full") -> dict:
    """Start a job for this user, or return the one already running."""
    with _lock:
        job = _jobs.get(user_id)
        if job and job.state == "running":
            return asdict(job)
        job = _jobs[user_id] = Job(user_id=user_id, kind=kind)
        snapshot = asdict(job)  # before the thread runs, so the caller always sees "running"
    threading.Thread(target=_run, args=(job, max_games, depth), daemon=True, name=f"analyze-{user_id}").start()
    return snapshot


def _progress(job: Job):
    weights = _WEIGHTS[job.kind]

    def report_(stage: str, done: int, total: int) -> None:
        lo, hi = weights.get(stage, (0, 100))
        frac = done / total if total else 0
        with _lock:
            job.stage, job.done, job.total = stage, done, total
            job.percent = max(job.percent, int(lo + (hi - lo) * frac))
            count = f" ({done} of {total})" if total > 1 else ""
            job.message = STAGE_TEXT.get(stage, stage) + count
    return report_


def build_and_save_report(session, user_id: int, progress=None) -> dict:
    """Build the gap report for the stored leaks and save it as the user's latest report."""
    user = session.get(User, user_id)
    leaks = pipeline.stored_leaks(session, user_id)
    rep = report.build_gap_report(leaks, mode="full", rating=user.rating if user else None, top=REPORT_TOP,
                                  budget_s=LLM_BUDGET_S, progress=progress)
    data = rep.model_dump(mode="json")
    row = session.scalars(select(SavedReport).where(SavedReport.user_id == user_id)).first()
    if row is None:
        row = SavedReport(user_id=user_id)
        session.add(row)
    row.content_json = data
    session.commit()
    return data


def make_quizzes(session, user_id: int, progress=None) -> int:
    made, _ = quiz.quizzes_from_leaks(session, user_id, limit=QUIZZES, progress=progress)
    for q in made:
        srs.schedule(session, q.id, user_id)
    return len(made)


def _run(job: Job, max_games: int, depth: int | None) -> None:
    progress = _progress(job)
    try:
        with SessionLocal() as session:
            summary: dict = {}
            if job.kind == "full":
                summary = pipeline.run_analysis(session, job.user_id, max_games=max_games, depth=depth,
                                                progress=progress).__dict__
            rep = build_and_save_report(session, job.user_id, progress)
            summary["report_items"] = len(rep["leaks"])
            summary["quizzes"] = make_quizzes(session, job.user_id, progress)
        with _lock:
            job.state, job.stage, job.percent, job.summary = "done", "done", 100, summary
            job.message = (f"Done: {summary['games_fetched']} games checked" if job.kind == "full"
                           else "Done: report rebuilt")
    except Exception as exc:  # noqa: BLE001 - the user gets a readable message, the log the trace
        log.exception("analysis job failed for user %s", job.user_id)
        with _lock:
            job.state, job.stage, job.error = "error", "error", str(exc) or exc.__class__.__name__
            job.message = STAGE_TEXT["error"]
    finally:
        job.finished_at = time.time()
