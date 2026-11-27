"""structured output with a mocked client, retry on malformed output."""

import pytest

from app.llm import client, prompts
from app.llm.client import FakeBackend, generate_structured
from app.schemas import LeakExplanation

GOOD = '{"reasoning": "r", "explanation": "e", "plan": "p", "memory_aid": "m", "citations": ["idea-x"]}'


@pytest.fixture(autouse=True)
def _reset_backend():
    yield
    client.set_backend(None)


def test_validated_object_returned() -> None:
    client.set_backend(FakeBackend([GOOD]))
    out = generate_structured("prompt", LeakExplanation)
    assert isinstance(out, LeakExplanation) and out.citations == ["idea-x"]


def test_malformed_response_triggers_retry() -> None:
    fake = FakeBackend(["not json at all", '{"explanation": 3}', GOOD])
    client.set_backend(fake)
    out = generate_structured("prompt", LeakExplanation)
    assert out.plan == "p"
    assert len(fake.calls) == 3
    # The validation error is fed back to the model.
    assert "rejected" in fake.calls[1]["messages"][-1]["content"]


def test_gives_up_after_max_retries() -> None:
    client.set_backend(FakeBackend(["{}", "{}", "{}"]))
    with pytest.raises(ValueError):
        generate_structured("prompt", LeakExplanation)


def test_extra_check_reasons_are_fed_back() -> None:
    fake = FakeBackend([GOOD.replace("idea-x", "idea-fake"), GOOD])
    client.set_backend(fake)
    out = generate_structured("p", LeakExplanation,
                              extra_check=lambda o: [] if o.citations == ["idea-x"] else ["bad citation"])
    assert out.citations == ["idea-x"]
    assert "bad citation" in fake.calls[1]["messages"][-1]["content"]


def test_code_fences_are_tolerated() -> None:
    client.set_backend(FakeBackend(["```json\n" + GOOD + "\n```"]))
    assert generate_structured("p", LeakExplanation).explanation == "e"


def test_unavailable_without_key() -> None:
    client.set_backend(None)
    assert not client.is_available()


def test_prompts_contain_rules_and_facts() -> None:
    p = prompts.leak_diagnosis({"played_san": "Nxe5"}, [{"id": "idea-a", "title": "t", "text": "x"}])
    assert "Never name a move that is not in FACTS" in p and "[idea-a]" in p and "Nxe5" in p
    assert "beginner" not in prompts.system_prompt(1900)
    assert prompts.level_for(1100) == "beginner"
