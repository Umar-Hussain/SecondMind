"""Phase 25: API end to end — sign up, upload a repertoire, analyse, inspect, train."""

import itertools

import pytest
from fastapi.testclient import TestClient

from app.config import FIXTURES_DIR
from app.main import app

pytestmark = pytest.mark.usefixtures("require_engine")
_ids = itertools.count(1)


@pytest.fixture(scope="module")
def api():
    with TestClient(app) as c:
        yield c


def signup(api, **profile) -> dict:
    """Create a fresh account and return auth headers."""
    name = f"player{next(_ids)}"
    res = api.post("/auth/signup", json={"username": name, "password": "correct-horse", **profile}).json()
    return {"Authorization": f"Bearer {res['token']}"}


def test_full_user_journey(api) -> None:
    h = signup(api, lichess_username="demo_player", chesscom_username="demo_player_cc", rating=1600)

    pgn = (FIXTURES_DIR / "repertoire_white.pgn").read_text()
    rep = api.post("/repertoires", headers=h, json={"name": "e4 as White", "color": "white", "pgn": pgn}).json()
    assert rep["saved"] and rep["nodes"] > 10

    summary = api.post("/analyze?depth=10", headers=h, json={}).json()
    assert summary["games_new"] > 20 and summary["deviations"] >= 3

    devs = api.get(f"/deviations?repertoire_id={rep['id']}", headers=h).json()
    counts = [d["games_count"] for d in devs]
    assert counts == sorted(counts, reverse=True)
    detail = api.get(f"/deviations/{devs[0]['id']}", headers=h).json()
    assert detail["fen"] and detail["explanation"] and detail["generated_by"] == "template"
    assert "master_stats" in detail

    unc = api.get(f"/uncovered?repertoire_id={rep['id']}", headers=h).json()
    assert unc[0]["opponent_san"] == "d5"

    report = api.get("/report?top=3&depth=10", headers=h).json()
    assert report["leaks"] and all(i["verified"] for i in report["leaks"])
    assert api.get("/report?mode=llm", headers=h).status_code == 422  # unguarded modes are never served

    api.post("/quiz/generate?depth=10", headers=h)
    nxt = api.get("/quiz/next", headers=h).json()["quiz"]
    assert nxt is not None
    res = api.post(f"/quiz/{nxt['id']}/answer", headers=h, json={"move_uci": "a2a3"}).json()
    assert "correct" in res and res["interval_days"] >= 1

    prog = api.get("/progress", headers=h).json()
    assert prog["open_leaks"] >= 1 and prog["quizzes"] >= 1


def test_bad_repertoire_reports_errors(api) -> None:
    h = signup(api)
    res = api.post("/repertoires", headers=h, json={"name": "bad", "color": "white",
                                                    "moves_text": "1.e4 e5 2.Ke3"}).json()
    assert not res["saved"] and "move 2" in res["issues"][0]["location"]


def test_live_analysis_websocket(api) -> None:
    with api.websocket_connect("/ws/analysis") as wsock:
        wsock.send_json({"fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"})
        msg = wsock.receive_json()
        assert msg["type"] == "info" and msg["lines"] and "masters" in msg
        wsock.send_json({"fen": "not a fen"})
        for _ in range(200):
            m = wsock.receive_json()
            if m["type"] == "error":
                break
        assert m["type"] == "error"


def test_recommend_and_ics(api) -> None:
    h = signup(api)
    rec = api.get("/recommend", headers=h, params={"fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                                                   "depth": 10}).json()
    assert rec["chosen_source"] in ("master", "engine") and rec["verified"]
    from datetime import datetime, timezone

    from app.services.delivery import briefing_ics

    ics = briefing_ics("rival_player", 1, datetime(2026, 12, 1, 18, 0, tzinfo=timezone.utc))
    assert "BEGIN:VCALENDAR" in ics and "Prep vs rival_player" in ics


def test_api_prefix_and_built_site(api) -> None:
    """Production layout: the web app calls /api/... and the site itself is served at /."""
    from app.config import ROOT_DIR

    assert api.get("/api/engine/status").json()["app"] == "SecondMind"
    if (ROOT_DIR / "frontend" / "dist" / "index.html").exists():
        page = api.get("/")
        assert page.status_code == 200 and "<div id=\"root\">" in page.text


def test_unexpected_errors_return_json() -> None:
    """A crash inside a route comes back as JSON with a reference, not a plain-text page."""
    from fastapi import APIRouter

    boom = APIRouter()

    @boom.get("/__boom")
    def _boom() -> dict:
        raise RuntimeError("kaboom")

    app.include_router(boom)
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/__boom")
    assert r.status_code == 500 and "reference" in r.json()["detail"] and "kaboom" not in r.text
    status = TestClient(app).get("/engine/status").json()
    assert status["database"] in ("sqlite", "postgresql") and status["version"]
