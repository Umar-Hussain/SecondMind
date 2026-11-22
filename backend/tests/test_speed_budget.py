"""Interactive pages must not hang on a rate-limited free LLM tier."""

import time

import pytest

from app.llm import client
from app.services import report


class _Resp:
    status_code = 429
    headers = {"retry-after": "30"}
    text = "rate limited"


class _Http:
    headers: dict = {}

    def __init__(self):
        self.calls = 0

    def post(self, *a, **k):
        self.calls += 1
        return _Resp()


def test_time_budget_gives_up_instead_of_waiting() -> None:
    backend = client.OpenAICompatBackend("http://x", "m", http=_Http(), max_retries=3)
    start = time.monotonic()
    with client.time_budget(3), pytest.raises(client.LLMError):
        backend._post({})
    assert time.monotonic() - start < 2  # no 30 s sleep


def test_report_stops_asking_after_first_fallback(monkeypatch) -> None:
    calls = []

    class Item:
        def __init__(self, by):
            self.generated_by = by

    def fake_item(lk, mode, depth, rating, budget_s):
        calls.append(mode)
        return report.GapReportItem(opening="x", color="white", kind="mistake", position_fen="8/8/8/8/8/8/8/8 w - - 0 1",
                                    played="e2e4", recommended=None, eval_loss=1.0, generated_by="template")

    monkeypatch.setattr(report, "build_item", fake_item)
    monkeypatch.setattr(report.client, "is_available", lambda: True)

    class Lk:
        kind = "mistake"
    report.build_gap_report([Lk(), Lk(), Lk()], mode="full", budget_s=5)
    assert calls == ["full", "template", "template"]
