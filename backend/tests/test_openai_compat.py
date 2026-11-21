"""OpenAI-compatible backend (Groq / Ollama) against a mocked HTTP server."""

import json

import httpx
import pytest

from app.llm import client
from app.llm.client import LLMError, OpenAICompatBackend, generate_structured
from app.schemas import LeakExplanation

GOOD = {"reasoning": "r", "explanation": "e", "plan": "p", "memory_aid": "m", "citations": []}


def _completion(content=None, tool_calls=None, finish="stop") -> dict:
    msg = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {"choices": [{"message": msg, "finish_reason": finish}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 7}}


def _backend(handler) -> tuple[OpenAICompatBackend, list[dict]]:
    seen: list[dict] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append({"body": body, "auth": request.headers.get("authorization")})
        return handler(body, len(seen))

    http = httpx.Client(transport=httpx.MockTransport(wrapped))
    return OpenAICompatBackend("https://api.groq.test/openai/v1", "test-model", "gsk_test", http=http,
                               max_retries=2), seen


@pytest.fixture(autouse=True)
def _reset():
    yield
    client.set_backend(None)


def test_structured_uses_json_mode_and_validates(monkeypatch) -> None:
    be, seen = _backend(lambda body, n: httpx.Response(200, json=_completion(json.dumps(GOOD))))
    client.set_backend(be)
    out = generate_structured("prompt", LeakExplanation, system="sys")
    assert out.plan == "p"
    req = seen[0]["body"]
    assert req["response_format"] == {"type": "json_object"}
    assert req["messages"][0]["role"] == "system" and "JSON schema" in req["messages"][0]["content"]
    assert seen[0]["auth"] == "Bearer gsk_test"


def test_rate_limit_backs_off_then_succeeds(monkeypatch) -> None:
    monkeypatch.setattr(client.time, "sleep", lambda s: None)
    be, seen = _backend(lambda body, n: httpx.Response(429, headers={"retry-after": "1"}) if n == 1
                        else httpx.Response(200, json=_completion(json.dumps(GOOD))))
    client.set_backend(be)
    assert generate_structured("p", LeakExplanation).explanation == "e"
    assert len(seen) == 2


def test_quota_exhausted_raises_llm_error(monkeypatch) -> None:
    monkeypatch.setattr(client.time, "sleep", lambda s: None)
    be, _ = _backend(lambda body, n: httpx.Response(429))
    with pytest.raises(LLMError):
        be.text("", [{"role": "user", "content": "hi"}], 100)


def test_tool_round_trip_translation() -> None:
    """Tool calls come back as tool_use blocks; results go out as role=tool messages."""
    call = [{"id": "call_1", "type": "function", "function": {"name": "find_leaks", "arguments": '{"top": 3}'}}]
    be, seen = _backend(lambda body, n: httpx.Response(200, json=_completion(None, call, "tool_calls")) if n == 1
                        else httpx.Response(200, json=_completion("All done.")))
    tools = [{"name": "find_leaks", "description": "d", "input_schema": {"type": "object", "properties": {}}}]
    msgs: list[dict] = [{"role": "user", "content": "go"}]
    r1 = be.tools("sys", msgs, tools, 500)
    assert r1.stop_reason == "tool_use"
    use = r1.content[0]
    assert use == {"type": "tool_use", "id": "call_1", "name": "find_leaks", "input": {"top": 3}}
    msgs += [{"role": "assistant", "content": r1.content},
             {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": "{}"}]}]
    r2 = be.tools("sys", msgs, tools, 500)
    assert r2.text == "All done."
    sent = seen[1]["body"]["messages"]
    assert sent[2]["tool_calls"][0]["id"] == "call_1"
    assert sent[3] == {"role": "tool", "tool_call_id": "call_1", "content": "{}"}
    assert seen[0]["body"]["tools"][0]["function"]["name"] == "find_leaks"


def test_provider_settings_defaults() -> None:
    from app.config import Settings

    groq = Settings(llm_provider="groq", llm_api_key="k")
    assert groq.llm_enabled and groq.llm_settings[0] == "https://api.groq.com/openai/v1"
    assert not Settings(llm_provider="groq", llm_api_key="").llm_enabled
    ollama = Settings(llm_provider="ollama", llm_api_key="")
    assert ollama.llm_enabled and ollama.llm_settings[0].startswith("http://localhost:11434")


@pytest.mark.usefixtures("require_engine")
def test_report_falls_back_when_quota_is_gone(monkeypatch) -> None:
    from app.services.report import build_item
    from app.tools import chesscom, lichess
    from app.tools.games import merge_games
    from app.tools.leaks import mine_leaks

    monkeypatch.setattr(client.time, "sleep", lambda s: None)
    be, _ = _backend(lambda body, n: httpx.Response(429))
    client.set_backend(be)
    leaks = mine_leaks(merge_games(lichess.fetch_games("demo_player"), chesscom.fetch_games("demo_player_cc")),
                       depth=10)
    item = build_item(leaks[0], mode="full", depth=10)
    assert item.explanation.startswith("You played")  # deterministic template
    assert item.verified
