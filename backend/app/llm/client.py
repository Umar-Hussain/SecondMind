"""LLM wrapper: structured output, tool use, retries, logging.

Two backends share one interface:

* ``OpenAICompatBackend`` - any OpenAI-style ``/chat/completions`` endpoint:
  **Groq** (free tier, default), a local **Ollama** server, Gemini/OpenRouter.
* ``AnthropicBackend`` - Claude through the official SDK (paid, optional).

The provider is chosen with ``LLM_PROVIDER`` in ``.env``.

* ``generate_structured(prompt, schema)`` asks for JSON matching a Pydantic
  schema (constrained with ``messages.parse(output_format=...)``), validates
  it, and on failure retries up to 2 times with the validation error appended.
* ``create_with_tools(...)`` is one turn of the agent loop (``tool_choice`` is
  left on ``auto`` — forced tool choice is not supported on current models).
* Every call is logged to the ``runs`` table with latency and token counts.

The network call sits behind a small *backend* interface so tests (and the
no-LLM evaluation condition) can swap in a deterministic fake.
"""

from __future__ import annotations

import contextvars
import json
import time
from contextlib import contextmanager
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from app.config import get_settings
from app.runlog import log_run

T = TypeVar("T", bound=BaseModel)


class LLMUnavailable(RuntimeError):
    """No API key configured — callers fall back to deterministic templates."""


class LLMRefused(RuntimeError):
    """The model declined the request (``stop_reason == "refusal"``)."""


class LLMError(RuntimeError):
    """The provider failed (rate limit exhausted, network, server error).

    Callers treat it like a guard failure and fall back to templates, so a free
    tier running out of quota never breaks the app.
    """


@dataclass
class LLMReply:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = "end_turn"
    content: list[Any] = field(default_factory=list)  # raw content blocks (tool use)


class Backend(Protocol):
    def structured(self, system: str, messages: list[dict], schema: type[BaseModel], max_tokens: int) -> LLMReply: ...
    def text(self, system: str, messages: list[dict], max_tokens: int) -> LLMReply: ...
    def tools(self, system: str, messages: list[dict], tools: list[dict], max_tokens: int) -> LLMReply: ...


class AnthropicBackend:
    """Real backend on the official ``anthropic`` SDK."""

    def __init__(self, api_key: str, model: str, effort: str = "medium") -> None:
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key, max_retries=3, timeout=120.0)
        self.model = model
        self.effort = effort

    @staticmethod
    def _reply(resp: Any) -> LLMReply:
        if resp.stop_reason == "refusal":
            raise LLMRefused(getattr(resp.stop_details, "category", None) or "refused")
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        return LLMReply(text=text, input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens,
                        stop_reason=resp.stop_reason, content=list(resp.content))

    def structured(self, system, messages, schema, max_tokens):
        # Thinking is adaptive by default on this model; effort controls depth.
        resp = self._client.messages.parse(model=self.model, max_tokens=max_tokens, system=system,
                                           messages=messages, output_format=schema,
                                           output_config={"effort": self.effort})
        reply = self._reply(resp)
        parsed = getattr(resp, "parsed_output", None)
        if parsed is not None and not reply.text:
            reply.text = parsed.model_dump_json()
        return reply

    def text(self, system, messages, max_tokens):
        resp = self._client.messages.create(model=self.model, max_tokens=max_tokens, system=system,
                                            messages=messages, output_config={"effort": self.effort})
        return self._reply(resp)

    def tools(self, system, messages, tools, max_tokens):
        resp = self._client.messages.create(model=self.model, max_tokens=max_tokens, system=system,
                                            messages=messages, tools=tools, tool_choice={"type": "auto"},
                                            output_config={"effort": self.effort})
        return self._reply(resp)


class OpenAICompatBackend:
    """OpenAI-style chat completions over plain HTTP (no extra SDK needed).

    The rest of the code speaks the Anthropic message shape (content blocks,
    ``tool_use`` / ``tool_result``); this class translates both ways so the
    agent loop works unchanged on Groq or Ollama.
    """

    def __init__(self, base_url: str, model: str, api_key: str = "", http: Any = None,
                 max_retries: int = 3, timeout: float = 90.0, fail_fast: bool = False) -> None:
        import httpx

        if not base_url or not model:
            raise LLMUnavailable("LLM_BASE_URL and LLM_MODEL are required for this provider")
        self.base_url, self.model = base_url.rstrip("/"), model
        self.max_retries = max_retries
        self.fail_fast = fail_fast  # in a chain: on 429 hand over to the next model at once
        self.retry_after = 0.0  # last rate-limit wait the provider asked for
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._http = http or httpx.Client(timeout=timeout)
        self._http.headers.update(headers)

    # --- message translation (Anthropic shape -> OpenAI shape) ----------------
    @staticmethod
    def _get(b: Any, key: str) -> Any:
        return b.get(key) if isinstance(b, dict) else getattr(b, key, None)

    def _to_openai(self, system: str, messages: list[dict]) -> list[dict]:
        out: list[dict] = [{"role": "system", "content": system}] if system else []
        for m in messages:
            content = m["content"]
            if isinstance(content, str):
                out.append({"role": m["role"], "content": content})
                continue
            if m["role"] == "assistant":
                text = "".join(self._get(b, "text") or "" for b in content if self._get(b, "type") == "text")
                calls = [{"id": self._get(b, "id"), "type": "function",
                          "function": {"name": self._get(b, "name"),
                                       "arguments": json.dumps(self._get(b, "input") or {})}}
                         for b in content if self._get(b, "type") == "tool_use"]
                msg: dict = {"role": "assistant", "content": text or None}
                if calls:
                    msg["tool_calls"] = calls
                out.append(msg)
            else:  # user turn carrying tool results
                for b in content:
                    if self._get(b, "type") == "tool_result":
                        out.append({"role": "tool", "tool_call_id": self._get(b, "tool_use_id"),
                                    "content": self._get(b, "content")})
                    elif self._get(b, "type") == "text":
                        out.append({"role": "user", "content": self._get(b, "text")})
        return out

    # --- HTTP with backoff --------------------------------------------------------
    def _post(self, payload: dict) -> dict:
        import httpx

        delay = 2.0
        deadline = _deadline.get()
        for attempt in range(self.max_retries + 1):
            left = deadline - time.monotonic() if deadline else None
            if left is not None and left <= 1:
                raise LLMError("time budget used up")
            try:
                resp = self._http.post(f"{self.base_url}/chat/completions", json=payload,
                                       **({"timeout": left} if left is not None else {}))
            except httpx.HTTPError as exc:
                if attempt == self.max_retries:
                    raise LLMError(f"network error: {exc}") from exc
                time.sleep(delay)
                delay *= 2
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                self.retry_after = float(resp.headers.get("retry-after", 0) or 0)
                if self.fail_fast or attempt == self.max_retries:
                    raise LLMError(f"provider returned {resp.status_code} after {attempt + 1} attempts")
                wait = min(max(float(resp.headers.get("retry-after", 0) or 0), delay), 30.0)
                if deadline and time.monotonic() + wait > deadline:
                    # Inside a time budget (interactive pages): give up now, the caller falls back.
                    raise LLMError(f"provider returned {resp.status_code}; not waiting {wait:.0f}s")
                time.sleep(wait)
                delay *= 2
                continue
            if resp.status_code >= 400:
                raise LLMError(f"provider returned {resp.status_code}: {resp.text[:300]}")
            return resp.json()
        raise LLMError("unreachable")  # pragma: no cover

    @staticmethod
    def _reply(data: dict) -> LLMReply:
        choice = data["choices"][0]
        msg = choice["message"]
        usage = data.get("usage") or {}
        content: list[Any] = []
        if msg.get("content"):
            content.append({"type": "text", "text": msg["content"]})
        for call in msg.get("tool_calls") or []:
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"_raw": call["function"].get("arguments")}  # validate_args rejects it
            content.append({"type": "tool_use", "id": call["id"], "name": call["function"]["name"], "input": args})
        finish = choice.get("finish_reason")
        return LLMReply(text=msg.get("content") or "", input_tokens=usage.get("prompt_tokens", 0),
                        output_tokens=usage.get("completion_tokens", 0),
                        stop_reason="tool_use" if finish == "tool_calls" else (finish or "stop"), content=content)

    def structured(self, system, messages, schema, max_tokens):
        # JSON mode guarantees syntactically valid JSON; the schema is stated in the
        # system prompt and validated locally (generate_structured retries on errors).
        schema_txt = json.dumps(schema.model_json_schema())
        sys_prompt = (system + "\n\n" if system else "") + \
            f"Reply with one JSON object only, matching this JSON schema:\n{schema_txt}"
        return self._reply(self._post({"model": self.model, "messages": self._to_openai(sys_prompt, messages),
                                       "max_tokens": max_tokens, "temperature": 0.2,
                                       "response_format": {"type": "json_object"}}))

    def text(self, system, messages, max_tokens):
        return self._reply(self._post({"model": self.model, "messages": self._to_openai(system, messages),
                                       "max_tokens": max_tokens, "temperature": 0.3}))

    def tools(self, system, messages, tools, max_tokens):
        fns = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                 "parameters": t["input_schema"]}} for t in tools]
        return self._reply(self._post({"model": self.model, "messages": self._to_openai(system, messages),
                                       "tools": fns, "tool_choice": "auto", "max_tokens": max_tokens,
                                       "temperature": 0.2}))


class ChainBackend:
    """Several free models behind one interface (LLM_FALLBACKS).

    Each call goes to the first model that is not resting. When a model fails with a
    rate limit, a server error or a network error it rests for the time the provider asked
    (at least ``cooldown_s``) and the same call moves on to the next model, so a busy
    free tier never makes the user wait. Only if every model fails does the call fail
    (and the caller falls back to the verified template).
    """

    def __init__(self, members: list[tuple[str, Any]], cooldown_s: float = 60.0) -> None:
        self.members = members  # [(label, backend)]
        self.cooldown_s = cooldown_s
        self.resting: dict[str, float] = {}  # label -> monotonic time it may be used again
        self.last_used: str | None = None

    def _call(self, method: str, *args):
        errors = []
        now = time.monotonic()
        ready = [m for m in self.members if self.resting.get(m[0], 0) <= now]
        # If everything is resting, try the one that will be ready soonest anyway.
        order = ready or sorted(self.members, key=lambda m: self.resting.get(m[0], 0))[:1]
        for label, backend in order:
            if _deadline.get() and time.monotonic() >= _deadline.get():
                break
            try:
                reply = getattr(backend, method)(*args)
                self.last_used = label
                return reply
            except LLMError as exc:
                wait = max(self.cooldown_s, getattr(backend, "retry_after", 0) or 0)
                self.resting[label] = time.monotonic() + wait
                errors.append(f"{label}: {exc}")
        raise LLMError("all models busy: " + " | ".join(errors) if errors else "all models are resting")

    def structured(self, system, messages, schema, max_tokens):
        return self._call("structured", system, messages, schema, max_tokens)

    def text(self, system, messages, max_tokens):
        return self._call("text", system, messages, max_tokens)

    def tools(self, system, messages, tools, max_tokens):
        return self._call("tools", system, messages, tools, max_tokens)


class FakeBackend:
    """Deterministic backend for tests: returns queued replies in order."""

    def __init__(self, replies: list[str | LLMReply] | None = None,
                 responder: Callable[[str, list[dict]], str | LLMReply] | None = None) -> None:
        self.replies = list(replies or [])
        self.responder = responder
        self.calls: list[dict] = []

    def _next(self, system: str, messages: list[dict]) -> LLMReply:
        self.calls.append({"system": system, "messages": messages})
        if self.responder:
            r = self.responder(system, messages)
        elif self.replies:
            r = self.replies.pop(0)
        else:
            raise RuntimeError("FakeBackend has no more replies")
        return r if isinstance(r, LLMReply) else LLMReply(text=r, input_tokens=10, output_tokens=10)

    def structured(self, system, messages, schema, max_tokens):
        return self._next(system, messages)

    def text(self, system, messages, max_tokens):
        return self._next(system, messages)

    def tools(self, system, messages, tools, max_tokens):
        return self._next(system, messages)


_backend: Backend | None = None


def set_backend(backend: Backend | None) -> None:
    """Install a backend (tests, evaluation conditions). ``None`` resets to default."""
    global _backend
    _backend = backend


def get_backend() -> Backend:
    global _backend
    if _backend is None:
        s = get_settings()
        if not s.llm_enabled:
            raise LLMUnavailable(f"LLM provider '{s.llm_provider}' is not configured (missing API key)")
        if s.llm_provider.lower() == "anthropic":
            _backend = AnthropicBackend(s.anthropic_api_key, s.anthropic_model)
        else:
            base_url, model, key = s.llm_settings
            extra = s.llm_fallback_list
            if not extra:
                _backend = OpenAICompatBackend(base_url, model, key)
            else:
                members = [(f"{model}@{base_url.split('//')[-1].split('/')[0]}",
                            OpenAICompatBackend(base_url, model, key, max_retries=1, fail_fast=True))]
                members += [(f"{m}@{u.split('//')[-1].split('/')[0]}",
                             OpenAICompatBackend(u, m, k, max_retries=1, fail_fast=True)) for u, m, k in extra]
                _backend = ChainBackend(members, cooldown_s=s.llm_cooldown_s)
    return _backend


def is_available() -> bool:
    try:
        get_backend()
        return True
    except LLMUnavailable:
        return False


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t[3:]
        t = t.rsplit("```", 1)[0]
    return t.strip()


_deadline: contextvars.ContextVar[float | None] = contextvars.ContextVar("llm_deadline", default=None)


@contextmanager
def time_budget(seconds: float):
    """Limit every LLM call inside the block to ``seconds`` in total, retries and rate-limit
    waits included. Free tiers can ask for 30-90 s waits; a page should rather fall back to
    the verified template than make the user wait."""
    token = _deadline.set(time.monotonic() + seconds)
    try:
        yield
    finally:
        _deadline.reset(token)


def generate_structured(prompt: str, schema: type[T], system: str = "", name: str = "structured",
                        max_retries: int = 2, max_tokens: int = 4000,
                        extra_check: Callable[[T], list[str]] | None = None) -> T:
    """Return a validated ``schema`` instance, retrying with the error up to ``max_retries`` times.

    ``extra_check`` lets callers add domain checks (e.g. the verification guard);
    a non-empty list of reasons is fed back to the model exactly like a
    validation error.
    """
    backend = get_backend()
    messages: list[dict] = [{"role": "user", "content": prompt}]
    last_error = ""
    for attempt in range(max_retries + 1):
        start = time.perf_counter()
        reply = backend.structured(system, messages, schema, max_tokens)
        ms = (time.perf_counter() - start) * 1000
        try:
            obj = schema.model_validate(json.loads(_strip_fences(reply.text)))
            reasons = extra_check(obj) if extra_check else []
            if reasons:
                raise ValueError("; ".join(reasons))
            log_run("llm", name, {"prompt": prompt[:4000], "attempt": attempt}, {"text": reply.text[:4000]},
                    True, ms, reply.input_tokens, reply.output_tokens)
            return obj
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            last_error = str(exc)[:1500]
            log_run("llm", name, {"prompt": prompt[:4000], "attempt": attempt},
                    {"text": reply.text[:4000], "error": last_error}, False, ms, reply.input_tokens,
                    reply.output_tokens)
            messages = messages + [
                {"role": "assistant", "content": reply.text or "{}"},
                {"role": "user", "content": f"Your answer was rejected: {last_error}\n"
                                            "Return corrected JSON only, matching the schema exactly."},
            ]
    raise ValueError(f"{name}: no valid output after {max_retries + 1} attempts: {last_error}")


def generate_text(prompt: str, system: str = "", name: str = "text", max_tokens: int = 2000) -> str:
    backend = get_backend()
    start = time.perf_counter()
    reply = backend.text(system, [{"role": "user", "content": prompt}], max_tokens)
    log_run("llm", name, {"prompt": prompt[:4000]}, {"text": reply.text[:4000]}, True,
            (time.perf_counter() - start) * 1000, reply.input_tokens, reply.output_tokens)
    return reply.text


def create_with_tools(system: str, messages: list[dict], tools: list[dict], name: str = "agent",
                      max_tokens: int = 4000) -> LLMReply:
    backend = get_backend()
    start = time.perf_counter()
    reply = backend.tools(system, messages, tools, max_tokens)
    log_run("llm", name, {"turns": len(messages)}, {"text": reply.text[:2000], "stop": reply.stop_reason}, True,
            (time.perf_counter() - start) * 1000, reply.input_tokens, reply.output_tokens)
    return reply
