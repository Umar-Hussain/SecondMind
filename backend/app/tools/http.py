"""Polite HTTP helper shared by the Lichess and Chess.com clients.

* Retries with exponential backoff on HTTP 429 and 5xx (spec 14, risks table).
* A minimum delay between requests so we never hammer a public API.
* Fixture mode: ``OFFLINE=1`` reads saved responses, ``RECORD_FIXTURES=1``
  writes live responses to disk so they can be replayed later.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import httpx

from app.config import FIXTURES_DIR, get_settings


class NotFoundError(Exception):
    """Raised for HTTP 404 (unknown user, closed account...)."""


class RateLimitedError(Exception):
    """Raised when the API keeps answering 429 after all retries."""


_last_request_at: dict[str, float] = {}
_lock = threading.Lock()


def _respect_min_interval(host: str, min_interval: float) -> None:
    """Sleep so that consecutive requests to the same host are spaced out."""
    with _lock:
        last = _last_request_at.get(host, 0.0)
        wait = min_interval - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
        _last_request_at[host] = time.monotonic()


def get_text(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict | None = None,
    fixture: Path | None = None,
    max_retries: int = 4,
    min_interval: float = 1.0,
    timeout: float = 60.0,
) -> str:
    """GET ``url`` and return the body as text.

    ``fixture`` is the file used for offline replay / recording. A sibling file
    with the ``.404`` suffix marks a recorded "not found" response.
    """
    settings = get_settings()

    if settings.offline:
        if fixture is None:
            raise RuntimeError(f"OFFLINE=1 but no fixture path given for {url}")
        if fixture.with_suffix(".404").exists():
            raise NotFoundError(url)
        if not fixture.exists():
            raise NotFoundError(f"no fixture recorded at {fixture}")
        return fixture.read_text(encoding="utf-8")

    host = httpx.URL(url).host
    delay = 2.0
    for attempt in range(max_retries + 1):
        _respect_min_interval(host, min_interval)
        resp = httpx.get(url, headers=headers, params=params, timeout=timeout, follow_redirects=True)
        if resp.status_code == 404:
            if settings.record_fixtures and fixture is not None:
                fixture.parent.mkdir(parents=True, exist_ok=True)
                fixture.with_suffix(".404").write_text("")
            raise NotFoundError(url)
        if resp.status_code == 429 or resp.status_code >= 500:
            if attempt == max_retries:
                raise RateLimitedError(f"{url} -> {resp.status_code}")
            # Lichess asks clients to wait a full minute after a 429.
            retry_after = float(resp.headers.get("Retry-After", 0) or 0)
            time.sleep(max(delay, retry_after, 60.0 if resp.status_code == 429 and "lichess" in host else 0))
            delay *= 2
            continue
        resp.raise_for_status()
        if settings.record_fixtures and fixture is not None:
            fixture.parent.mkdir(parents=True, exist_ok=True)
            fixture.write_text(resp.text, encoding="utf-8")
        return resp.text
    raise RateLimitedError(url)  # pragma: no cover


def fixture_path(*parts: str) -> Path:
    return FIXTURES_DIR.joinpath(*parts)
