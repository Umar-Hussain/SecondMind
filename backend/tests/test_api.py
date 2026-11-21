"""Phase 25: API end to end — connect, upload a repertoire, analyse, inspect, train."""

import pytest
from fastapi.testclient import TestClient

from app.config import FIXTURES_DIR
from app.main import app

pytestmark = pytest.mark.usefixtures("require_engine")


@pytest.fixture(scope="module")
def api():
    with TestClient(app) as c:
        yield c


def test_full_user_journey(api) -> None:
    uid = api.post("/users", json={"lichess_username": "demo_player", "chesscom_username": "demo_player_cc",
                                   "rating": 1600}).json()["id"]

    pgn = (FIXTURES_DIR / "repertoire_white.pgn").read_text()
    rep = api.post("/repertoires", json={"user_id": uid, "name": "e4 as White", "color": "white", "pgn": pgn}).json()
    assert rep["saved"] and rep["nodes"] > 10

    summary = api.post("/analyze?depth=10", json={"user_id": uid}).json()
    assert summary["games_new"] > 20 and summary["deviations"] >= 3

    devs = api.get(f"/deviations?repertoire_id={rep['id']}").json()
    counts = [d["games_count"] for d in devs]
    assert counts == sorted(counts, reverse=True)
    detail = api.get(f"/deviations/{devs[0]['id']}").json()
    assert detail["fen"] and detail["explanation"] and detail["generated_by"] == "template"
    assert "master_stats" in detail

    unc = api.get(f"/uncovered?repertoire_id={rep['id']}").json()
    assert unc[0]["opponent_san"] == "d5"

    report = api.get(f"/report?user_id={uid}&top=3&depth=10").json()
    assert report["leaks"] and all(i["verified"] for i in report["leaks"])
    assert api.get(f"/report?user_id={uid}&mode=llm").status_code == 422  # unguarded modes are never served

    api.post(f"/quiz/generate?user_id={uid}&depth=10")
    nxt = api.get(f"/quiz/next?user_id={uid}").json()["quiz"]
    assert nxt is not None
    res = api.post(f"/quiz/{nxt['id']}/answer", json={"user_id": uid, "move_uci": "a2a3"}).json()
    assert "correct" in res and res["interval_days"] >= 1

    prog = api.get(f"/progress?user_id={uid}").json()
    assert prog["open_leaks"] >= 1 and prog["quizzes"] >= 1


def test_bad_repertoire_reports_errors(api) -> None:
    uid = api.post("/users", json={"lichess_username": "x"}).json()["id"]
    res = api.post("/repertoires", json={"user_id": uid, "name": "bad", "color": "white",
                                         "moves_text": "1.e4 e5 2.Ke3"}).json()
    assert not res["saved"] and "move 2" in res["issues"][0]["location"]


def test_live_analysis_websocket(api) -> None:
    with api.websocket_connect("/ws/analysis") as wsock:
        wsock.send_json({"fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"})
        msg = wsock.receive_json()
        assert msg["type"] == "info" and msg["lines"] and "masters" in msg
        wsock.send_json({"fen": "not a fen"})
        # Drain until the error for the bad FEN arrives.
        for _ in range(200):
            m = wsock.receive_json()
            if m["type"] == "error":
                break
        assert m["type"] == "error"


def test_recommend_and_ics(api) -> None:
    rec = api.get("/recommend", params={"fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                                        "depth": 10}).json()
    assert rec["chosen_source"] in ("master", "engine") and rec["verified"]
    from datetime import datetime, timezone

    from app.services.delivery import briefing_ics

    ics = briefing_ics("rival_player", 1, datetime(2026, 12, 1, 18, 0, tzinfo=timezone.utc))
    assert "BEGIN:VCALENDAR" in ics and "Prep vs rival_player" in ics


def test_api_prefix_and_built_site(api) -> None:
    """Production layout: the web app calls /api/... and the site itself is served at /."""
    from app.config import ROOT_DIR

    assert api.get("/api/engine/status").json()["stockfish"] in (True, False)
    if (ROOT_DIR / "frontend" / "dist" / "index.html").exists():
        page = api.get("/")
        assert page.status_code == 200 and "<div id=\"root\">" in page.text
