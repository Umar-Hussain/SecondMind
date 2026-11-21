"""Engine-verified quizzes from leaks and prepared lines (spec 5.11, 8.5, Phase 16).

* Position = the position before the leak; question "What is the best move here?".
* Correct answer = the recommender's move. When it came from the masters, the
  Stockfish best is also accepted if it is within the loss limit.
* In gambit lines the answer is the best gambit-keeping move and the question
  names the gambit, so the player is never asked to decline it.
* Validity (deterministic): the correct move must be within 30 cp of the best
  reference move, and the answer must be (nearly) unique — any *other* move
  within 30 cp is added to the accepted list, and a quiz with more than
  ``MAX_ACCEPTED`` acceptable answers is rejected as too ambiguous to grade.
"""

from __future__ import annotations

from dataclasses import dataclass

import chess
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Leak, Quiz
from app.schemas import QuizOut
from app.tools import engine, gambits
from app.tools.recommend import recommend_move

UNIQUE_CP = 30
MAX_ACCEPTED = 3


class QuizRejected(ValueError):
    pass


@dataclass
class QuizDraft:
    fen: str
    question: str
    correct: str
    accepted: list[str]
    eval_cp: int | None
    gambit_id: str | None
    explanation: str = ""


def build_quiz(fen: str, color: str, gambit_id: str | None = None, depth: int | None = None,
               opening: str = "") -> QuizDraft:
    """Build and validate one quiz; raises ``QuizRejected`` with the reason when invalid."""
    s = get_settings()
    board = chess.Board(fen)
    rec = recommend_move(fen, color, gambit_id=gambit_id, depth=depth)
    if not rec.verified:
        raise QuizRejected("recommended move failed verification")

    gdef = gambits.get(rec.gambit_id) if rec.gambit_id else None
    if gdef:
        theory = sorted(gambits.theory_moves_at(gdef, board))
        pool = engine.evaluate_moves(fen, sorted({*theory, rec.chosen_uci}), depth=depth)
    else:
        top = engine.evaluate(fen, depth=depth, multipv=5)
        pool = {line.move_uci: line.cp for line in top.lines}
        pool.update(engine.evaluate_moves(fen, [rec.chosen_uci], depth=depth))

    best_cp = max(pool.values())
    correct_cp = pool[rec.chosen_uci]
    if best_cp - correct_cp > UNIQUE_CP:
        raise QuizRejected(f"correct move is {best_cp - correct_cp} cp from the best")

    accepted = [rec.chosen_uci]
    for uci, cp in sorted(pool.items(), key=lambda kv: -kv[1]):
        if uci == rec.chosen_uci:
            continue
        within_limit = best_cp - cp <= s.max_loss_cp
        if (rec.chosen_source == "master" and uci == rec.engine_best_uci and within_limit) or \
                abs(correct_cp - cp) <= UNIQUE_CP:
            accepted.append(uci)
    if len(accepted) > MAX_ACCEPTED:
        raise QuizRejected(f"{len(accepted)} moves are equally good: too ambiguous")

    who = "White" if board.turn == chess.WHITE else "Black"
    if gdef:
        question = f"{gdef.name}: you play the gambit as {who}. What is the best move that keeps the gambit going?"
    else:
        question = f"{opening + ': ' if opening else ''}{who} to move. What is the best move here?"
    return QuizDraft(fen=fen, question=question, correct=rec.chosen_uci, accepted=accepted, eval_cp=correct_cp,
                     gambit_id=rec.gambit_id, explanation=rec.reason)


def save_quiz(session: Session, draft: QuizDraft, leak_id: int | None = None) -> Quiz:
    """Insert unless an identical (fen, answer) quiz exists — keeps jobs idempotent."""
    existing = session.scalars(select(Quiz).where(Quiz.fen == draft.fen,
                                                  Quiz.correct_move_uci == draft.correct)).first()
    if existing:
        return existing
    row = Quiz(leak_id=leak_id, fen=draft.fen, question=draft.question, correct_move_uci=draft.correct,
               accepted_moves_json=draft.accepted, explanation=draft.explanation, engine_eval_cp=draft.eval_cp,
               gambit_id=draft.gambit_id)
    session.add(row)
    session.commit()
    return row


def quizzes_from_leaks(session: Session, user_id: int, depth: int | None = None, limit: int = 10
                       ) -> tuple[list[Quiz], list[str]]:
    """One quiz per open leak (gambit notes excluded). Returns (quizzes, rejection reasons)."""
    leaks = session.scalars(select(Leak).where(Leak.user_id == user_id, Leak.status == "open",
                                               Leak.kind != "gambit_note")).all()
    made, rejected = [], []
    for lk in leaks[:limit]:
        try:
            draft = build_quiz(lk.fen_before, lk.color, lk.gambit_id, depth=depth, opening=lk.opening_name or "")
        except QuizRejected as exc:
            rejected.append(f"leak {lk.id}: {exc}")
            continue
        made.append(save_quiz(session, draft, lk.id))
    return made, rejected


def check_answer(quiz: Quiz, move_uci: str) -> bool:
    return move_uci in (quiz.accepted_moves_json or [quiz.correct_move_uci])


def to_out(q: Quiz) -> QuizOut:
    return QuizOut(id=q.id, fen=q.fen, question=q.question, correct_move_uci=q.correct_move_uci,
                   accepted_moves=list(q.accepted_moves_json or []), explanation=q.explanation, gambit_id=q.gambit_id)
