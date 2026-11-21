"""Audit log for LLM calls, tool calls, verification results and jobs (spec 14).

Every entry goes to the ``runs`` table. Logging must never break the main
flow, so failures to write are swallowed after printing a warning.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from app.db import SessionLocal
from app.models import Run


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def log_run(kind: str, name: str, input: Any = None, output: Any = None, ok: bool = True,
            latency_ms: float = 0.0, input_tokens: int = 0, output_tokens: int = 0) -> None:
    try:
        with SessionLocal() as s:
            s.add(Run(kind=kind, name=name, input_json=_jsonable(input or {}), output_json=_jsonable(output or {}),
                      ok=ok, latency_ms=latency_ms, input_tokens=input_tokens, output_tokens=output_tokens))
            s.commit()
    except Exception as exc:  # pragma: no cover - logging is best effort
        print(f"[runlog] could not write {kind}/{name}: {exc}")


@contextmanager
def timed(kind: str, name: str, input: Any = None) -> Iterator[dict]:
    """Context manager that logs latency and whatever the caller puts in ``out``."""
    out: dict[str, Any] = {"ok": True}
    start = time.perf_counter()
    try:
        yield out
    except Exception as exc:
        out["ok"] = False
        out["error"] = repr(exc)
        raise
    finally:
        ms = (time.perf_counter() - start) * 1000
        log_run(kind, name, input, out.get("output", {k: v for k, v in out.items() if k != "ok"}), out["ok"], ms,
                out.get("input_tokens", 0), out.get("output_tokens", 0))
