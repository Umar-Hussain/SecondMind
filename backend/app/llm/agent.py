"""Agent orchestrator with tool calling (spec 4, 9.4, Phase 13).

The model plans the workflow and calls deterministic tools; this module runs
the loop:

1. send the task, the system prompt and the tool schemas;
2. for every ``tool_use`` block: validate the arguments, run the real
   function, return the result (or the error) as a ``tool_result``;
3. repeat until the model answers without tools or ``MAX_STEPS`` is reached.

Every tool call is logged to ``runs`` (audit trail). Tool results are kept
compact: big objects (games, leaks) stay in ``AgentState`` and the model only
sees counts and ids, which keeps the context small and prevents the model from
"reading" moves it could then misquote.

Named workflows (``analyze_player``, ``prepare_for_opponent``, ``review_game``,
``daily_training``) wrap the loop with a task description. Without an API key
they run a fixed deterministic plan over the same tools (evaluation condition 0).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.llm import client
from app.models import User
from app.runlog import log_run
from app.schemas import GapReport
from app.services import pipeline, report
from app.tools import engine, gambits, quiz, rag, srs
from app.tools.openings import classify
from app.tools.recommend import recommend_move
from app.tools.verify import verify_line


@dataclass
class AgentState:
    session: Session
    user_id: int
    depth: int | None = None
    leaks: list = field(default_factory=list)
    report: GapReport | None = None
    briefing: dict | None = None
    quizzes: list[int] = field(default_factory=list)
    messages_sent: list[str] = field(default_factory=list)
    trail: list[dict] = field(default_factory=list)


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    fn: Callable[[AgentState, dict], Any]

    def spec(self) -> dict:
        return {"name": self.name, "description": self.description, "input_schema": self.schema}


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


FEN = {"type": "string", "description": "Position in FEN"}


# --- Tool implementations -----------------------------------------------------


def t_fetch_games(st: AgentState, a: dict) -> dict:
    s = pipeline.run_analysis(st.session, st.user_id, max_games=a.get("max_games", 200), depth=st.depth)
    st.leaks = pipeline.stored_leaks(st.session, st.user_id)
    return {"games_fetched": s.games_fetched, "new_games": s.games_new, "warnings": s.warnings,
            "note": "games stored and mined; call find_leaks to see the ranked leaks"}


def t_classify_opening(st: AgentState, a: dict) -> dict:
    moves = a["moves_uci"]
    if not verify_line("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", moves).ok:
        raise ValueError("move list is not legal from the start position")
    return classify(moves).model_dump()


def t_detect_gambit(st: AgentState, a: dict) -> dict:
    m = gambits.detect_gambit(a["moves_uci"], a["color"])
    if m is None:
        return {"gambit": None}
    return {"gambit": m.gambit.name, "id": m.gambit.id, "played_by_user": m.played_by_user,
            "soundness": m.gambit.soundness}


def t_find_leaks(st: AgentState, a: dict) -> dict:
    if not st.leaks:
        st.leaks = pipeline.stored_leaks(st.session, st.user_id)
    top = st.leaks[: a.get("top", 5)]
    return {"count": len(st.leaks), "top": [
        {"index": i, "opening": lk.opening_name, "kind": lk.kind, "color": lk.color, "frequency": lk.frequency,
         "avg_loss_cp": lk.avg_loss, "fen": lk.fen} for i, lk in enumerate(top)]}


def t_evaluate_position(st: AgentState, a: dict) -> dict:
    res = engine.evaluate(a["fen"], depth=st.depth, multipv=3)
    return {"cp_white": res.cp_white, "best": res.best_move_uci,
            "lines": [{"san": " ".join(x.pv_san[:6]), "cp_side_to_move": x.cp} for x in res.lines]}


def t_retrieve_theory(st: AgentState, a: dict) -> dict:
    docs = rag.retrieve(a["query"], eco=a.get("eco"), k=a.get("k", 4))
    return {"docs": [{"id": d.id, "title": d.citation.title, "text": d.text[:500]} for d in docs]}


def t_recommend_move(st: AgentState, a: dict) -> dict:
    r = recommend_move(a["fen"], a.get("side"), gambit_id=a.get("gambit_id"), depth=st.depth)
    return {"move": r.chosen_san, "uci": r.chosen_uci, "source": r.chosen_source, "reason": r.reason,
            "verified": r.verified}


def t_build_report(st: AgentState, a: dict) -> dict:
    if not st.leaks:
        st.leaks = pipeline.stored_leaks(st.session, st.user_id)
    user = st.session.get(User, st.user_id)
    st.report = report.build_gap_report(st.leaks, mode="full", depth=st.depth, rating=user.rating if user else None,
                                        top=a.get("top", 5))
    return {"items": len(st.report.leaks), "all_verified": all(i.verified for i in st.report.leaks)}


def t_scout_opponent(st: AgentState, a: dict) -> dict:
    from app.services.briefing import prepare

    b, bid = prepare(st.session, st.user_id, a["opponent"], a.get("platform", "lichess"), depth=st.depth)
    st.briefing = {"id": bid, **b.model_dump(mode="json")}
    return {"briefing_id": bid, "likely_openings": b.likely_openings, "extra_lines": len(b.extra_lines),
            "risks": b.risks[:3]}


def t_build_quiz(st: AgentState, a: dict) -> dict:
    made, rejected = quiz.quizzes_from_leaks(st.session, st.user_id, depth=st.depth, limit=a.get("limit", 5))
    st.quizzes = [q.id for q in made]
    return {"created": len(made), "quiz_ids": st.quizzes, "rejected": rejected[:5]}


def t_schedule_review(st: AgentState, a: dict) -> dict:
    ids = a.get("quiz_ids") or st.quizzes
    for qid in ids:
        srs.schedule(st.session, qid, st.user_id)
    return {"scheduled": len(ids)}


def t_send_message(st: AgentState, a: dict) -> dict:
    # Delivery happens through services.delivery; here we only queue verified text.
    st.messages_sent.append(a["text"])
    return {"queued": True}


TOOLS: dict[str, Tool] = {t.name: t for t in [
    Tool("fetch_games", "Fetch the player's recent games from Lichess and Chess.com, store them and mine "
         "opening leaks and repertoire deviations.", _obj({"max_games": {"type": "integer", "minimum": 1,
                                                                          "maximum": 500}}, []), t_fetch_games),
    Tool("classify_opening", "ECO classification of a move list (UCI).",
         _obj({"moves_uci": {"type": "array", "items": {"type": "string"}}}, ["moves_uci"]), t_classify_opening),
    Tool("detect_gambit", "Detect whether a game follows a known gambit and who sacrificed.",
         _obj({"moves_uci": {"type": "array", "items": {"type": "string"}},
               "color": {"type": "string", "enum": ["white", "black"]}}, ["moves_uci", "color"]), t_detect_gambit),
    Tool("find_leaks", "Return the player's ranked opening leaks (already engine-verified).",
         _obj({"top": {"type": "integer", "minimum": 1, "maximum": 20}}, []), t_find_leaks),
    Tool("evaluate_position", "Stockfish evaluation and top 3 lines for a FEN.", _obj({"fen": FEN}, ["fen"]),
         t_evaluate_position),
    Tool("retrieve_theory", "Retrieve opening theory passages with citation ids.",
         _obj({"query": {"type": "string"}, "eco": {"type": "string"}, "k": {"type": "integer"}}, ["query"]),
         t_retrieve_theory),
    Tool("recommend_move", "Practical move recommendation (masters vs Stockfish) for a position.",
         _obj({"fen": FEN, "side": {"type": "string", "enum": ["white", "black"]},
               "gambit_id": {"type": "string"}}, ["fen"]), t_recommend_move),
    Tool("build_gap_report", "Build the verified, cited gap report for the top leaks.",
         _obj({"top": {"type": "integer", "minimum": 1, "maximum": 10}}, []), t_build_report),
    Tool("scout_opponent", "Scout an opponent and prepare a briefing with extra lines.",
         _obj({"opponent": {"type": "string"}, "platform": {"type": "string", "enum": ["lichess", "chesscom"]}},
              ["opponent"]), t_scout_opponent),
    Tool("suggest_prep_lines", "Alias of scout_opponent that returns the extra preparation lines.",
         _obj({"opponent": {"type": "string"}}, ["opponent"]), t_scout_opponent),
    Tool("build_quiz", "Create engine-verified quizzes from the player's open leaks.",
         _obj({"limit": {"type": "integer", "minimum": 1, "maximum": 20}}, []), t_build_quiz),
    Tool("schedule_review", "Schedule spaced-repetition reviews for quizzes.",
         _obj({"quiz_ids": {"type": "array", "items": {"type": "integer"}}}, []), t_schedule_review),
    Tool("send_message", "Queue a short message to the player in the web app.",
         _obj({"text": {"type": "string"}}, ["text"]), t_send_message),
]}


def validate_args(tool: Tool, args: Any) -> dict:
    """Minimal JSON-schema validation: object, required keys, no unknown keys, basic types."""
    if not isinstance(args, dict):
        raise ValueError("arguments must be a JSON object")
    props = tool.schema["properties"]
    missing = [k for k in tool.schema["required"] if k not in args]
    unknown = [k for k in args if k not in props]
    if missing or unknown:
        raise ValueError(f"missing {missing}, unknown {unknown}")
    types = {"string": str, "integer": int, "array": list, "object": dict, "boolean": bool}
    for k, v in args.items():
        t = props[k].get("type")
        if t in types and not isinstance(v, types[t]):
            raise ValueError(f"'{k}' must be of type {t}")
        if "enum" in props[k] and v not in props[k]["enum"]:
            raise ValueError(f"'{k}' must be one of {props[k]['enum']}")
    return args


def run_tool(st: AgentState, name: str, args: Any) -> tuple[str, bool]:
    """Execute one tool call; return (json result, is_error). Errors are fed back, never raised."""
    start = time.perf_counter()
    tool = TOOLS.get(name)
    try:
        if tool is None:
            raise ValueError(f"unknown tool '{name}'")
        result = tool.fn(st, validate_args(tool, args))
        if result in (None, {}, []):
            result = {"empty": True, "note": "the tool returned nothing; try different arguments"}
        ok, payload = True, result
    except Exception as exc:  # feed the error back so the model can adapt
        ok, payload = False, {"error": f"{type(exc).__name__}: {exc}"}
    ms = (time.perf_counter() - start) * 1000
    st.trail.append({"tool": name, "args": args, "ok": ok, "ms": round(ms, 1)})
    log_run("tool", name, args, payload, ok, ms)
    return json.dumps(payload, default=str)[:6000], not ok


AGENT_SYSTEM = """You are RepertoireAI's orchestrator, a chess second working for one club player.
Plan the work, call tools to get every chess fact, react to errors and empty results, and finish
with a short plain-language summary for the player. Never state a move, evaluation or source that
did not come from a tool result in this conversation."""


@dataclass
class AgentResult:
    final_text: str
    steps: int
    trail: list[dict]
    stopped_by: str  # end_turn | max_steps | fallback


def _block(b: Any, key: str) -> Any:
    return b.get(key) if isinstance(b, dict) else getattr(b, key, None)


def run_agent(st: AgentState, task: str, max_steps: int | None = None) -> AgentResult:
    max_steps = max_steps or get_settings().agent_max_steps
    tools = [t.spec() for t in TOOLS.values()]
    messages: list[dict] = [{"role": "user", "content": task}]
    for step in range(1, max_steps + 1):
        reply = client.create_with_tools(AGENT_SYSTEM, messages, tools, name="agent")
        uses = [b for b in reply.content if _block(b, "type") == "tool_use"]
        if not uses:
            log_run("agent", "finish", {"task": task}, {"steps": step, "trail": st.trail}, True)
            return AgentResult(reply.text, step, st.trail, "end_turn")
        # Pass the assistant turn back unchanged (thinking blocks included), then all results in ONE user turn.
        messages.append({"role": "assistant", "content": reply.content})
        results = []
        for b in uses:
            out, is_err = run_tool(st, _block(b, "name"), _block(b, "input"))
            results.append({"type": "tool_result", "tool_use_id": _block(b, "id"), "content": out,
                            "is_error": is_err})
        messages.append({"role": "user", "content": results})
    log_run("agent", "max_steps", {"task": task}, {"trail": st.trail}, False)
    return AgentResult("Stopped: step limit reached.", max_steps, st.trail, "max_steps")


# --- Named workflows ---------------------------------------------------------------

FALLBACK_PLANS: dict[str, list[tuple[str, dict]]] = {
    "analyze_player": [("fetch_games", {}), ("find_leaks", {"top": 5}), ("build_gap_report", {"top": 5})],
    "daily_training": [("find_leaks", {"top": 5}), ("build_quiz", {"limit": 5}), ("schedule_review", {})],
}


def _run_plan(st: AgentState, name: str, extra: dict | None = None) -> AgentResult:
    plan = [(t, {**a, **(extra or {})} if t == "scout_opponent" else a) for t, a in FALLBACK_PLANS[name]]
    for tool, args in plan:
        run_tool(st, tool, args)
    return AgentResult(f"Completed {name} with the deterministic plan.", len(plan), st.trail, "fallback")


def analyze_player(session: Session, user_id: int, depth: int | None = None) -> tuple[AgentResult, GapReport | None]:
    st = AgentState(session=session, user_id=user_id, depth=depth)
    res: AgentResult | None = None
    if client.is_available():
        try:
            res = run_agent(st, "Analyze my recent games: fetch them, find my recurring opening leaks, and build "
                                "my gap report for the top 5. Then summarize the three most important points.")
        except (client.LLMError, client.LLMRefused) as exc:  # e.g. free-tier quota used up
            log_run("agent", "provider_failed", {"workflow": "analyze_player"}, {"error": str(exc)}, False)
    if res is None:
        st.trail.clear()
        res = _run_plan(st, "analyze_player")
    elif st.report is None:  # the model forgot the last step: finish it deterministically
        run_tool(st, "build_gap_report", {"top": 5})
    return res, st.report


def prepare_for_opponent(session: Session, user_id: int, opponent: str, platform: str = "lichess",
                         depth: int | None = None) -> tuple[AgentResult, dict | None]:
    st = AgentState(session=session, user_id=user_id, depth=depth)
    res: AgentResult | None = None
    if client.is_available():
        try:
            res = run_agent(st, f"Prepare me for my next game against '{opponent}' on {platform}. Scout them, "
                                "build the briefing, and tell me the two things to remember.")
        except (client.LLMError, client.LLMRefused) as exc:
            log_run("agent", "provider_failed", {"workflow": "prepare_for_opponent"}, {"error": str(exc)}, False)
    if res is None or st.briefing is None:
        run_tool(st, "scout_opponent", {"opponent": opponent, "platform": platform})
        res = AgentResult("Briefing prepared with the deterministic plan.", len(st.trail), st.trail, "fallback")
    return res, st.briefing


def daily_training(session: Session, user_id: int, depth: int | None = None) -> AgentResult:
    st = AgentState(session=session, user_id=user_id, depth=depth)
    return _run_plan(st, "daily_training")
