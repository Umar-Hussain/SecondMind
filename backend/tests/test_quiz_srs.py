"""Phase 16: SM-2 intervals and engine-checked quiz validity."""

from datetime import datetime, timedelta, timezone

import chess
import pytest

from app.models import User
from app.tools.pgn_utils import san_line_to_uci
from app.tools.quiz import QuizRejected, build_quiz, check_answer, save_quiz
from app.tools.srs import SM2State, get_due, grade_review, schedule, sm2

DEPTH = 12


def _fen(moves: str) -> str:
    b = chess.Board()
    for u in san_line_to_uci(moves):
        b.push_uci(u)
    return b.fen()


def test_sm2_intervals_1_6_then_ease() -> None:
    s = sm2(SM2State(), 5)
    assert (s.repetitions, s.interval_days) == (1, 1)
    s = sm2(s, 5)
    assert (s.repetitions, s.interval_days) == (2, 6)
    ease_before = s.ease
    s = sm2(s, 5)
    assert s.interval_days == round(6 * ease_before)


def test_sm2_failure_resets() -> None:
    s = sm2(sm2(sm2(SM2State(), 5), 5), 2)
    assert s.repetitions == 0 and s.interval_days == 1
    assert s.ease >= 1.3


def test_sm2_rejects_bad_grade() -> None:
    with pytest.raises(ValueError):
        sm2(SM2State(), 7)


@pytest.mark.usefixtures("require_engine")
def test_quiz_from_blunder_position(db) -> None:
    # Position before the planted 4.Nxe5?? — the answer must not be Nxe5.
    fen = _fen("e4 e5 Nf3 Nc6 Bb5 a6")
    draft = build_quiz(fen, "white", depth=DEPTH, opening="Ruy Lopez")
    assert draft.correct != "f3e5"
    assert "Ruy Lopez" in draft.question
    quiz = save_quiz(db, draft)
    assert check_answer(quiz, draft.correct) and not check_answer(quiz, "f3e5")
    # Saving again is idempotent.
    assert save_quiz(db, draft).id == quiz.id


@pytest.mark.usefixtures("require_engine")
def test_gambit_quiz_names_the_gambit() -> None:
    draft = build_quiz(_fen("e4 e5 d4 exd4 c3 dxc3"), "white", gambit_id="danish_gambit", depth=DEPTH)
    assert "Danish Gambit" in draft.question
    assert draft.correct == "f1c4"


@pytest.mark.usefixtures("require_engine")
def test_ambiguous_quiz_is_rejected() -> None:
    # The start position has many equally good moves.
    with pytest.raises(QuizRejected):
        build_quiz(chess.STARTING_FEN, "white", depth=DEPTH)


@pytest.mark.usefixtures("require_engine")
def test_due_queue_and_grading(db) -> None:
    user = User(lichess_username="u")
    db.add(user)
    db.commit()
    quiz = save_quiz(db, build_quiz(_fen("e4 e5 Nf3 Nc6 Bb5 a6"), "white", depth=DEPTH))
    schedule(db, quiz.id, user.id)
    schedule(db, quiz.id, user.id)  # idempotent
    assert [q.id for q in get_due(db, user.id)] == [quiz.id]
    now = datetime.now(timezone.utc)
    review = grade_review(db, quiz.id, user.id, 5, now=now)
    assert review.interval_days == 1
    assert get_due(db, user.id, now=now) == []
    assert get_due(db, user.id, now=now + timedelta(days=2))
