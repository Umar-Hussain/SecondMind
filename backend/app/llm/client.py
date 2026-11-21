"""Anthropic (Claude) wrapper: structured output, tool use, retries, logging (spec 9.1, Phase 12).

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

import json
import time
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
            raise LLMUnavailable("ANTHROPIC_API_KEY is not set")
        _backend = AnthropicBackend(s.anthropic_api_key, s.anthropic_model)
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
