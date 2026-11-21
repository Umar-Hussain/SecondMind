"""REST API (spec 11.1, Phase 25).

Thin layer: every route validates input, calls a tool or service, and returns
already-verified objects. No chess fact is created here.
"""

from __future__ import annotations

from datetime import datetime, timezone

import chess
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.llm import agent
from app.models import Briefing as BriefingRow, Game, Leak, Quiz, Repertoire, RepertoireDeviation, Review, \
    UncoveredLine, User
from app.schemas import AccountLink, AnalyzeRequest, QuizAnswer, RepertoireCreate, ScoutRequest, UserCreate
from app.services import pipeline, report
from app.services.briefing import prepare
from app.services.delivery import briefing_ics
from app.tools import deviations, engine, masters, quiz, srs
from app.tools.openings import classify
from app.tools.pgn_utils import board_from_key, uci_to_san
from app.tools.recommend import recommend_move
from app.tools.repertoire import (
    edit_node, import_lichess_study, import_moves_text, import_pgn, load_tree, save_tree, tree_to_json,
)

router = APIRouter()


def _user(session: Session, user_id: int) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "user not found")
    return user


# --- Users and accounts ----------------------------------------------------------


@router.post("/users")
def create_user(body: UserCreate, session: Session = Depends(get_session)) -> dict:
    if not (body.lichess_username or body.chesscom_username):
        raise HTTPException(422, "link at least one of Lichess or Chess.com")
    user = User(lichess_username=body.lichess_username, chesscom_username=body.chesscom_username, rating=body.rating)
    session.add(user)
    session.commit()
    return {"id": user.id, "lichess_username": user.lichess_username, "chesscom_username": user.chesscom_username}


@router.post("/accounts")
def link_account(body: AccountLink, session: Session = Depends(get_session)) -> dict:
    user = _user(session, body.user_id)
    if body.platform == "lichess":
        user.lichess_username = body.username
    else:
        user.chesscom_username = body.username
    session.commit()
    return {"id": user.id, "lichess_username": user.lichess_username, "chesscom_username": user.chesscom_username}


@router.get("/users/{user_id}")
def get_user(user_id: int, session: Session = Depends(get_session)) -> dict:
    u = _user(session, user_id)
    n = session.scalar(select(func.count()).select_from(Game).where(Game.user_id == user_id))
    return {"id": u.id, "lichess_username": u.lichess_username, "chesscom_username": u.chesscom_username,
            "rating": u.rating, "games": n}


# --- Repertoires -------------------------------------------------------------------


def _save_rep(session: Session, user_id: int, name: str, color: str, pgn: str | None, moves_text: str | None,
              study_url: str | None, intentional_gambit: bool) -> dict:
    if pgn:
        tree, source = import_pgn(pgn, color, name), "pgn"
    elif moves_text:
        tree, source = import_moves_text(moves_text, color, name), "text"
    elif study_url:
        tree, source = import_lichess_study(study_url, color, name), "study"
    else:
        raise HTTPException(422, "provide pgn, moves_text or study_url")
    issues = [{"level": i.level, "location": i.location, "message": i.message} for i in tree.issues]
    if tree.errors:
        return {"id": None, "saved": False, "issues": issues}
    rep = save_tree(session, user_id, tree, source, pgn or moves_text or "", intentional_gambit)
    return {"id": rep.id, "saved": True, "issues": issues, "nodes": len(tree.nodes)}


@router.post("/repertoires")
def create_repertoire(body: RepertoireCreate, session: Session = Depends(get_session)) -> dict:
    _user(session, body.user_id)
    return _save_rep(session, body.user_id, body.name, body.color, body.pgn, body.moves_text, body.study_url,
                     body.intentional_gambit)


@router.post("/repertoires/upload")
async def upload_repertoire(user_id: int = Form(...), name: str = Form(...), color: str = Form(...),
                            intentional_gambit: bool = Form(False), file: UploadFile = File(...),
                            session: Session = Depends(get_session)) -> dict:
    _user(session, user_id)
    if color not in ("white", "black"):
        raise HTTPException(422, "color must be white or black")
    text = (await file.read()).decode("utf-8", errors="replace")
    return _save_rep(session, user_id, name, color, text, None, None, intentional_gambit)


@router.get("/repertoires")
def list_repertoires(user_id: int, session: Session = Depends(get_session)) -> list[dict]:
    reps = session.scalars(select(Repertoire).where(Repertoire.user_id == user_id)).all()
    return [{"id": r.id, "name": r.name, "color": r.color, "status": r.status, "source": r.source_type,
             "intentional_gambit": r.intentional_gambit} for r in reps]


@router.get("/repertoires/{rep_id}/tree")
def repertoire_tree(rep_id: int, session: Session = Depends(get_session)) -> dict:
    try:
        return tree_to_json(load_tree(session, rep_id))
    except KeyError:
        raise HTTPException(404, "repertoire not found")


class NodeEdit(BaseModel):
    fen_key: str
    user_move: str | None = None
    add_alternative: str | None = None
    add_opponent_move: str | None = None
    comment: str | None = None


@router.patch("/repertoires/{rep_id}/nodes")
def patch_node(rep_id: int, body: NodeEdit, session: Session = Depends(get_session)) -> dict:
    try:
        row = edit_node(session, rep_id, body.fen_key, user_move=body.user_move,
                        add_alternative=body.add_alternative, add_opponent_move=body.add_opponent_move,
                        comment=body.comment)
    except KeyError:
        raise HTTPException(404, "repertoire not found")
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {"fen_key": row.fen_key, "user_move": row.user_move_uci, "alternatives": row.alternative_moves_json,
            "opponent_moves": row.opponent_moves_json}


# --- Analysis, leaks, deviations ------------------------------------------------------


@router.post("/analyze")
def analyze(body: AnalyzeRequest, depth: int | None = Query(None, ge=6, le=22),
            session: Session = Depends(get_session)) -> dict:
    _user(session, body.user_id)
    summary = pipeline.run_analysis(session, body.user_id, max_games=body.max_games, depth=depth)
    return summary.__dict__


@router.get("/leaks")
def get_leaks(user_id: int, session: Session = Depends(get_session)) -> list[dict]:
    out = []
    for lk in session.scalars(select(Leak).where(Leak.user_id == user_id)):
        out.append({"id": lk.id, "opening": lk.opening_name, "eco": lk.opening_eco, "color": lk.color,
                    "kind": lk.kind, "fen": lk.fen_before, "played": lk.played_move,
                    "played_san": uci_to_san(lk.fen_before, lk.played_move), "theory_move": lk.theory_move,
                    "theory_san": uci_to_san(lk.fen_before, lk.theory_move) if lk.theory_move else None,
                    "eval_loss_cp": lk.eval_loss_cp, "frequency": lk.frequency, "status": lk.status,
                    "gambit_id": lk.gambit_id})
    return sorted(out, key=lambda x: (x["kind"] == "gambit_note", -x["frequency"] * max(x["eval_loss_cp"], 1)))


@router.get("/report")
def get_report(user_id: int, top: int = 8, mode: str = "full", depth: int | None = Query(None, ge=6, le=22),
               session: Session = Depends(get_session)) -> dict:
    if mode not in ("full", "template"):
        raise HTTPException(422, "only verified modes (full, template) are served to users")
    user = _user(session, user_id)
    leaks = pipeline.stored_leaks(session, user_id)
    return report.build_gap_report(leaks, mode=mode, depth=depth, rating=user.rating, top=top).model_dump(mode="json")


@router.get("/deviations")
def list_deviations(repertoire_id: int, sort: str = "games", session: Session = Depends(get_session)) -> list[dict]:
    rep = session.get(Repertoire, repertoire_id)
    if rep is None:
        raise HTTPException(404, "repertoire not found")
    devs = deviations.load_deviations(session, repertoire_id, rep.color, sort=sort)
    return [d.model_dump(mode="json") for d in devs]


@router.get("/deviations/{dev_id}")
def deviation_detail(dev_id: int, session: Session = Depends(get_session)) -> dict:
    row = session.get(RepertoireDeviation, dev_id)
    if row is None:
        raise HTTPException(404, "deviation not found")
    rep = session.get(Repertoire, row.repertoire_id)
    dev = next(d for d in deviations.load_deviations(session, rep.id, rep.color) if d.id == dev_id)
    fen = board_from_key(dev.node_fen).fen()
    board = chess.Board(fen)
    opening = classify([m.uci() for m in board.move_stack]) if board.move_stack else None
    user = session.get(User, rep.user_id) if rep.user_id else None
    expl, docs, by = report.explain_deviation(dev, opening.name if opening else rep.name,
                                              opening.eco if opening else None, user.rating if user else None)
    stats = masters.master_moves(fen)
    return {**dev.model_dump(mode="json"), "fen": fen, "repertoire_name": rep.name,
            "explanation": expl.explanation, "plan": expl.plan, "memory_aid": expl.memory_aid,
            "citations": [d.citation.model_dump() for d in docs if d.id in expl.citations],
            "generated_by": by, "master_stats": stats.model_dump(mode="json")}


@router.get("/uncovered")
def uncovered(repertoire_id: int, session: Session = Depends(get_session)) -> list[dict]:
    rows = session.scalars(select(UncoveredLine).where(UncoveredLine.repertoire_id == repertoire_id)
                           .order_by(UncoveredLine.games_count.desc()))
    out = []
    for r in rows:
        fen = board_from_key(r.node_fen_key).fen()
        after = chess.Board(fen)
        after.push_uci(r.opponent_move)
        out.append({"id": r.id, "fen": fen, "opponent_move": r.opponent_move,
                    "opponent_san": uci_to_san(fen, r.opponent_move), "games_count": r.games_count,
                    "suggested_reply": r.suggested_reply, "fen_after": after.fen(),
                    "suggested_san": uci_to_san(after.fen(), r.suggested_reply) if r.suggested_reply else None})
    return out


@router.get("/recommend")
def recommend(fen: str, side: str | None = None, gambit_id: str | None = None,
              depth: int | None = Query(None, ge=6, le=22)) -> dict:
    try:
        chess.Board(fen)
    except ValueError:
        raise HTTPException(422, "invalid FEN")
    return recommend_move(fen, side, gambit_id=gambit_id, depth=depth).model_dump(mode="json")


@router.get("/masters")
def master_stats(fen: str) -> dict:
    return masters.master_moves(fen).model_dump(mode="json")


# --- Scouting and briefing ---------------------------------------------------------------


@router.post("/scout")
def scout_opponent(body: ScoutRequest, depth: int | None = Query(None, ge=6, le=22),
                   session: Session = Depends(get_session)) -> dict:
    _user(session, body.user_id)
    briefing, bid = prepare(session, body.user_id, body.opponent, body.platform, depth=depth,
                            max_games=body.max_games)
    return {"briefing_id": bid, **briefing.model_dump(mode="json")}


@router.get("/briefing/{briefing_id}")
def get_briefing(briefing_id: int, session: Session = Depends(get_session)) -> dict:
    row = session.get(BriefingRow, briefing_id)
    if row is None:
        raise HTTPException(404, "briefing not found")
    return {"briefing_id": row.id, "created_at": row.created_at.isoformat(), **row.content_json}


@router.get("/briefing/{briefing_id}/ics", response_class=PlainTextResponse)
def get_briefing_ics(briefing_id: int, game_time: datetime, session: Session = Depends(get_session)) -> str:
    row = session.get(BriefingRow, briefing_id)
    if row is None:
        raise HTTPException(404, "briefing not found")
    return briefing_ics(row.opponent, briefing_id, game_time)


# --- Training ----------------------------------------------------------------------------------


@router.post("/quiz/generate")
def generate_quizzes(user_id: int, depth: int | None = Query(None, ge=6, le=22),
                     session: Session = Depends(get_session)) -> dict:
    res = agent.daily_training(session, user_id, depth=depth)
    return {"trail": res.trail}


@router.get("/quiz/next")
def next_quiz(user_id: int, session: Session = Depends(get_session)) -> dict:
    due = srs.get_due(session, user_id, limit=1)
    if not due:
        return {"quiz": None}
    q = due[0]
    return {"quiz": {"id": q.id, "fen": q.fen, "question": q.question, "gambit_id": q.gambit_id}}


@router.post("/quiz/{quiz_id}/answer")
def answer_quiz(quiz_id: int, body: QuizAnswer, session: Session = Depends(get_session)) -> dict:
    q = session.get(Quiz, quiz_id)
    if q is None:
        raise HTTPException(404, "quiz not found")
    correct = quiz.check_answer(q, body.move_uci)
    review = srs.grade_review(session, quiz_id, body.user_id, 5 if correct else 1)
    return {"correct": correct, "correct_move": q.correct_move_uci, "correct_san": uci_to_san(q.fen, q.correct_move_uci),
            "accepted": q.accepted_moves_json, "explanation": q.explanation,
            "next_due": review.due_at.isoformat(), "interval_days": review.interval_days}


@router.get("/progress")
def progress(user_id: int, session: Session = Depends(get_session)) -> dict:
    leaks = session.scalars(select(Leak).where(Leak.user_id == user_id)).all()
    reviews = session.scalars(select(Review).where(Review.user_id == user_id)).all()
    graded = [r for r in reviews if r.last_result is not None]
    real = [lk for lk in leaks if lk.kind != "gambit_note"]
    return {
        "open_leaks": sum(1 for lk in real if lk.status == "open"),
        "plugged_leaks": sum(1 for lk in real if lk.status == "plugged"),
        "avg_opening_loss_cp": round(sum(lk.eval_loss_cp for lk in real) / len(real), 1) if real else 0,
        "repeat_mistake_rate": round(sum(1 for lk in real if lk.frequency > 1) / len(real), 2) if real else 0,
        "quizzes": len(reviews),
        "quiz_accuracy": round(sum(1 for r in graded if r.last_result >= 3) / len(graded), 2) if graded else None,
        "as_of": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/engine/status")
def engine_status() -> dict:
    s = get_settings()
    return {"stockfish": engine.is_available(), "llm": bool(s.anthropic_api_key), "model": s.anthropic_model,
            "offline": s.offline}
