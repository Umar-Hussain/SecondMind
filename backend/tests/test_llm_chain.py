"""Several free models: switch to the next one when one is rate limited."""

import pytest

from app.config import Settings
from app.llm import client


class _Resp:
    def __init__(self, code, body=None, retry=0):
        self.status_code, self._body = code, body
        self.headers = {"retry-after": str(retry)}
        self.text = "x"

    def json(self):
        return self._body


OK = {"choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}], "usage": {}}


class _Http:
    headers: dict = {}

    def __init__(self, codes):
        self.codes, self.calls = list(codes), 0

    def post(self, *a, **k):
        self.calls += 1
        code = self.codes.pop(0) if self.codes else 200
        return _Resp(code, OK, retry=120 if code == 429 else 0)


def _member(name, codes):
    http = _Http(codes)
    return (name, client.OpenAICompatBackend("http://x", name, http=http, max_retries=1, fail_fast=True)), http


def test_busy_model_hands_over_and_rests() -> None:
    (a, ha), (b, hb) = _member("a", [429]), _member("b", [])
    chain = client.ChainBackend([a, b], cooldown_s=60)
    assert chain.text("", [{"role": "user", "content": "hi"}], 10).text == "hello"
    assert chain.last_used == "b" and ha.calls == 1  # no waiting, no retry on 429
    chain.text("", [{"role": "user", "content": "hi"}], 10)
    assert ha.calls == 1 and chain.last_used == "b"  # "a" is resting (provider asked 120 s)


def test_all_busy_raises_so_the_template_is_used() -> None:
    (a, _), (b, _) = _member("a", [429]), _member("b", [503])
    chain = client.ChainBackend([a, b], cooldown_s=60)
    with pytest.raises(client.LLMError, match="all models busy"):
        chain.text("", [{"role": "user", "content": "hi"}], 10)


def test_fallback_setting_is_parsed() -> None:
    s = Settings(llm_fallbacks="gemini|gemini-2.5-flash|K1; bad entry ;https://my.host/v1|m|K2\nmistral|mistral-small-latest|K3",
                 _env_file=None)
    assert s.llm_fallback_list == [
        ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-flash", "K1"),
        ("https://my.host/v1", "m", "K2"),
        ("https://api.mistral.ai/v1", "mistral-small-latest", "K3"),
    ]
