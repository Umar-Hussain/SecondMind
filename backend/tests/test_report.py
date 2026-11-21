"""Phase 14: gap report — verified moves and valid citations for every leak."""

import pytest

from app.llm import client
from app.llm.client import FakeBackend
from app.models import User
from app.services.pipeline import run_analysis, stored_leaks
from app.services.report import build_gap_report, build_item
from app.tools import chesscom, lichess, verify
from app.tools.games import merge_games
from app.tools.leaks import mine_leaks

pytestmark = pytest.mark.usefixtures("require_engine")
DEPTH = 12


@pytest.fixture(autouse=True)
def _reset():
    yield
    client.set_backend(None)


@pytest.fixture(scope="module")
def fixture_leaks():
    games = merge_games(lichess.fetch_games("demo_player"), chesscom.fetch_games("demo_player_cc"))
    return mine_leaks(games, depth=DEPTH)


def _check_item(item) -> None:
    if item.recommended:
        assert verify.is_legal(item.position_fen, item.recommended)
    assert verify.is_legal(item.position_fen, item.played)
    assert item.verified


def test_template_report_is_verified(fixture_leaks) -> None:
    report = build_gap_report(fixture_leaks, mode="template", depth=DEPTH)
    assert report.generated_by == "template"
    assert report.leaks[0].played_san == "Nxe5"
    for item in report.leaks:
        _check_item(item)
    notes = [i for i in report.leaks if i.is_gambit_note]
    assert notes and all("information only" in n.explanation for n in notes)


def test_llm_hallucinated_move_falls_back_to_template(fixture_leaks) -> None:
    # The fake model keeps inventing "Qh5" and a fake source; the guard rejects it twice.
    bad = '{"explanation": "Play Qh5 instead [idea-made-up].", "plan": "p", "memory_aid": "", "citations": ["idea-made-up"]}'
    client.set_backend(FakeBackend([bad, bad]))
    item = build_item(fixture_leaks[0], mode="full", depth=DEPTH)
    assert "Qh5" not in item.explanation
    assert all(c.id != "idea-made-up" for c in item.citations)


def test_llm_grounded_answer_is_kept(fixture_leaks) -> None:
    leak = fixture_leaks[0]
    def responder(system, messages):
        prompt = messages[0]["content"]
        doc_id = "idea-ruy-morphy" if "[idea-ruy-morphy]" in prompt else None
        cite = f" [{doc_id}]" if doc_id else ""
        return ('{"reasoning": "r", "explanation": "Nxe5 ignores the attack on the bishop.", '
                f'"plan": "Retreat with Ba4 and castle{cite}.", "memory_aid": "Answer threats first.", '
                f'"citations": {[doc_id] if doc_id else []}}}'.replace("'", '"'))
    client.set_backend(FakeBackend(responder=responder))
    item = build_item(leak, mode="full", depth=DEPTH)
    assert item.explanation.startswith("Nxe5 ignores")
    assert all(c.id for c in item.citations)


def test_pipeline_end_to_end(db) -> None:
    user = User(lichess_username="demo_player", chesscom_username="demo_player_cc")
    db.add(user)
    db.commit()
    summary = run_analysis(db, user.id, depth=DEPTH)
    assert summary.games_new > 20 and summary.leaks >= 5
    leaks = stored_leaks(db, user.id)
    assert leaks[0].played == "f3e5"
    assert leaks[0].theory_move  # filled by the recommender
