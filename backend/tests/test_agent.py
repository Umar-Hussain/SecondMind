"""Phase 13: agent loop on fixtures with a scripted model."""

from types import SimpleNamespace

import pytest

from app.llm import agent, client
from app.llm.client import FakeBackend, LLMReply
from app.models import User

pytestmark = pytest.mark.usefixtures("require_engine")


@pytest.fixture(autouse=True)
def _reset():
    yield
    client.set_backend(None)


def _tool(id_: str, name: str, inp: dict) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=inp)


def _user(db) -> int:
    u = User(lichess_username="demo_player", chesscom_username="demo_player_cc", rating=1600)
    db.add(u)
    db.commit()
    return u.id


def test_validate_args() -> None:
    t = agent.TOOLS["evaluate_position"]
    with pytest.raises(ValueError):
        agent.validate_args(t, {})
    with pytest.raises(ValueError):
        agent.validate_args(t, {"fen": "x", "bogus": 1})
    with pytest.raises(ValueError):
        agent.validate_args(agent.TOOLS["detect_gambit"], {"moves_uci": [], "color": "green"})


def test_analyze_player_without_llm_uses_plan(db) -> None:
    uid = _user(db)
    res, report = agent.analyze_player(db, uid, depth=10)
    assert res.stopped_by == "fallback"
    assert report and report.leaks and all(i.verified for i in report.leaks)
    assert [t["tool"] for t in res.trail] == ["fetch_games", "find_leaks", "build_gap_report"]


def test_agent_loop_feeds_errors_back_and_finishes(db) -> None:
    uid = _user(db)
    script = [
        LLMReply(text="", content=[_tool("t1", "evaluate_position", {})], stop_reason="tool_use"),  # bad args
        LLMReply(text="", content=[_tool("t2", "fetch_games", {"max_games": 50})], stop_reason="tool_use"),
        LLMReply(text="", content=[_tool("t3", "find_leaks", {"top": 3}),
                                   _tool("t4", "build_gap_report", {"top": 3})], stop_reason="tool_use"),
        LLMReply(text="Your biggest leak is in the Ruy Lopez.", content=[], stop_reason="end_turn"),
    ]
    safe = '{"explanation": "This move ignores the main threat.", "plan": "Develop first.", "citations": []}'

    def responder(system, messages):
        return script.pop(0) if "orchestrator" in system else safe

    fake = FakeBackend(responder=responder)
    client.set_backend(fake)
    res, report = agent.analyze_player(db, uid, depth=10)
    assert res.stopped_by == "end_turn" and res.steps == 4
    assert res.trail[0]["ok"] is False  # validation error was fed back...
    assert all(t["ok"] for t in res.trail[1:])  # ...and the model recovered
    # Both tool results of step 3 came back in ONE user message.
    agent_calls = [c for c in fake.calls if "orchestrator" in c["system"]]
    last_user = agent_calls[-1]["messages"][-1]
    assert last_user["role"] == "user" and len(last_user["content"]) == 2
    assert report and report.leaks


def test_step_limit(db) -> None:
    uid = _user(db)
    loop = LLMReply(text="", content=[_tool("x", "find_leaks", {})], stop_reason="tool_use")
    client.set_backend(FakeBackend(responder=lambda s, m: loop))
    st = agent.AgentState(session=db, user_id=uid)
    res = agent.run_agent(st, "loop forever", max_steps=3)
    assert res.stopped_by == "max_steps" and res.steps == 3
