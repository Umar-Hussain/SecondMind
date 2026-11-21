"""REST API (spec 11.1, Phase 25).

Thin layer: every route validates input, calls a tool or service, and returns
already-verified objects. No chess fact is created here.

Access control: every user route takes the logged-in user from the bearer token
(``auth.current_user``); a ``user_id`` sent by the client is ignored. Users can
only read and change their own repertoires, plus *read* library repertoires.
Admins publish the library.
"""

from __future__ import annotations

from datetime import datetime, timezone

import chess
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import (
    current_user, hash_password, issue_token, public_user, require_admin, validate_new_account,
    verify_password,
)
from app.config import get_settings
from app.db import get_session
from app.llm import agent
from app.models import Briefing as BriefingRow, Game, Leak, Quiz, Repertoire, RepertoireDeviation, Review, \
    UncoveredLine, User
from app.schemas import (
    AnalyzeRequest, LoginRequest, ProfileUpdate, QuizAnswer, RepertoireCreate, ScoutRequest, SignupRequest,
)
from app.services import pipeline, report
from app.services.briefing import prepare
from app.services.delivery import briefing_ics
from app.tools import deviations, engine, masters, quiz, srs
from app.tools.openings import classify
from app.tools.pgn_utils import board_from_key, uci_to_san
from app.tools.recommend import recommend_move
from app.tools.repertoire import (
    copy_repertoire, delete_repertoire, edit_node, import_lichess_study, import_moves_text, import_pgn,
    load_tree, remove_move, save_tree, tree_to_json,
)

router = APIRouter()


# --- Access helpers -----------------------------------------------------------------


def _readable_rep(session: Session, rep_id: int, user: User) -> Repertoire:
    """Own repertoires, library repertoires, or anything for an admin."""
    rep = session.get(Repertoire, rep_id)
    if rep is None or not (rep.user_id == user.id or rep.is_library or user.role == "admin"):
        raise HTTPException(404, "repertoire not found")
    return rep


def _writable_rep(session: Session, rep_id: int, user: User) -> Repertoire:
    """Own repertoires; library repertoires only for admins."""
    rep = _readable_rep(session, rep_id, user)
    if rep.is_library and user.role != "admin":
        raise HTTPException(403, "Library repertoires are read-only: add it to your repertoires to edit it")
    if not rep.is_library and rep.user_id != user.id:
        raise HTTPException(403, "not your repertoire")
    return rep


def _rep_summary(r: Repertoire, owner: str | None = None) -> dict:
    return {"id": r.id, "name": r.name, "color": r.color, "status": r.status, "source": r.source_type,
            "intentional_gambit": r.intentional_gambit, "is_library": r.is_library,
            "description": r.description or "", "copied_from_id": r.copied_from_id, "owner": owner,
            "created_at": r.created_at.isoformat() if r.created_at else None}


# --- Accounts -------------------------------------------------------------------------


@router.post("/auth/signup")
def signup(body: SignupRequest, session: Session = Depends(get_session)) -> dict:
    name = validate_new_account(body.username, body.password)
    if session.scalars(select(User).where(User.username == name)).first():
        raise HTTPException(409, "That username is taken")
    user = User(username=name, password_hash=hash_password(body.password), role="user",
                display_name=(body.display_name or body.username).strip(),
                lichess_username=body.lichess_username or None, chesscom_username=body.chesscom_username or None,
                rating=body.rating)
    session.add(user)
    session.commit()
    return {"token": issue_token(user.id), "user": public_user(user)}


@router.post("/auth/login")
def login(body: LoginRequest, session: Session = Depends(get_session)) -> dict:
    user = session.scalars(select(User).where(User.username == body.username.strip().lower())).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Wrong username or password")
    return {"token": issue_token(user.id), "user": public_user(user)}


@router.get("/auth/me")
def me(user: User = Depends(current_user), session: Session = Depends(get_session)) -> dict:
    n = session.scalar(select(func.count()).select_from(Game).where(Game.user_id == user.id))
    return {**public_user(user), "games": n}


@router.patch("/auth/me")
def update_me(body: ProfileUpdate, user: User = Depends(current_user), session: Session = Depends(get_session)
              ) -> dict:
    user = session.merge(user)
    for field in ("display_name", "lichess_username", "chesscom_username", "rating"):
        value = getattr(body, field)
        if value is not None:
            setattr(user, field, value or None)
    session.commit()
    return public_user(user)


# --- Repertoires ------------------------------------------------------------------------


def _save_rep(session: Session, owner_id: int, name: str, color: str, pgn: str | None, moves_text: str | None,
              study_url: str | None, intentional_gambit: bool, library: bool = False, description: str = "") -> dict:
    if color not in ("white", "black"):
        raise HTTPException(422, "color must be white or black")
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
    rep = save_tree(session, owner_id, tree, source, pgn or moves_text or "", intentional_gambit)
    rep.is_library, rep.description = library, description
    session.commit()
    return {"id": rep.id, "saved": True, "issues": issues, "nodes": len(tree.nodes)}


@router.post("/repertoires")
def create_repertoire(body: RepertoireCreate, user: User = Depends(current_user),
                      session: Session = Depends(get_session)) -> dict:
    return _save_rep(session, user.id, body.name, body.color, body.pgn, body.moves_text, body.study_url,
                     body.intentional_gambit, description=body.description)


@router.post("/repertoires/upload")
async def upload_repertoire(name: str = Form(...), color: str = Form(...), intentional_gambit: bool = Form(False),
                            file: UploadFile = File(...), user: User = Depends(current_user),
                            session: Session = Depends(get_session)) -> dict:
    text = (await file.read()).decode("utf-8", errors="replace")
    return _save_rep(session, user.id, name, color, text, None, None, intentional_gambit)


@router.get("/repertoires")
def list_repertoires(user: User = Depends(current_user), session: Session = Depends(get_session)) -> list[dict]:
    reps = session.scalars(select(Repertoire).where(Repertoire.user_id == user.id,
                                                    Repertoire.is_library.is_(False))).all()
    return [_rep_summary(r) for r in reps]


@router.get("/repertoires/{rep_id}/tree")
def repertoire_tree(rep_id: int, user: User = Depends(current_user), session: Session = Depends(get_session)) -> dict:
    rep = _readable_rep(session, rep_id, user)
    return {**tree_to_json(load_tree(session, rep_id)), **_rep_summary(rep)}


class NodeEdit(BaseModel):
    fen_key: str
    user_move: str | None = None
    add_alternative: str | None = None
    add_opponent_move: str | None = None
    comment: str | None = None


@router.patch("/repertoires/{rep_id}/nodes")
def patch_node(rep_id: int, body: NodeEdit, user: User = Depends(current_user),
               session: Session = Depends(get_session)) -> dict:
    _writable_rep(session, rep_id, user)
    try:
        row = edit_node(session, rep_id, body.fen_key, user_move=body.user_move,
                        add_alternative=body.add_alternative, add_opponent_move=body.add_opponent_move,
                        comment=body.comment)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {"fen_key": row.fen_key, "user_move": row.user_move_uci, "alternatives": row.alternative_moves_json,
            "opponent_moves": row.opponent_moves_json}


class MoveRemoval(BaseModel):
    fen_key: str
    move: str


@router.post("/repertoires/{rep_id}/remove-move")
def delete_move(rep_id: int, body: MoveRemoval, user: User = Depends(current_user),
                session: Session = Depends(get_session)) -> dict:
    _writable_rep(session, rep_id, user)
    try:
        pruned = remove_move(session, rep_id, body.fen_key, body.move)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {"removed_positions": pruned}


class RepertoireUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    intentional_gambit: bool | None = None


@router.patch("/repertoires/{rep_id}")
def update_repertoire(rep_id: int, body: RepertoireUpdate, user: User = Depends(current_user),
                      session: Session = Depends(get_session)) -> dict:
    rep = _writable_rep(session, rep_id, user)
    for field in ("name", "description", "intentional_gambit"):
        value = getattr(body, field)
        if value is not None:
            setattr(rep, field, value)
    session.commit()
    return _rep_summary(rep)


@router.delete("/repertoires/{rep_id}")
def remove_repertoire(rep_id: int, user: User = Depends(current_user), session: Session = Depends(get_session)
                      ) -> dict:
    _writable_rep(session, rep_id, user)
    delete_repertoire(session, rep_id)
    return {"deleted": rep_id}


# --- Library (published by admins, readable and copyable by everyone) ----------------------


@router.get("/library")
def library(user: User = Depends(current_user), session: Session = Depends(get_session)) -> list[dict]:
    reps = session.scalars(select(Repertoire).where(Repertoire.is_library.is_(True))
                           .order_by(Repertoire.created_at.desc())).all()
    owners = {u.id: u.display_name or u.username for u in session.scalars(select(User))}
    mine = {r.copied_from_id for r in session.scalars(select(Repertoire).where(Repertoire.user_id == user.id))}
    return [{**_rep_summary(r, owners.get(r.user_id)), "in_my_repertoires": r.id in mine} for r in reps]


@router.post("/library")
def publish(body: RepertoireCreate, admin: User = Depends(require_admin),
            session: Session = Depends(get_session)) -> dict:
    return _save_rep(session, admin.id, body.name, body.color, body.pgn, body.moves_text, body.study_url,
                     body.intentional_gambit, library=True, description=body.description)


class CopyRequest(BaseModel):
    name: str | None = None


@router.post("/library/{rep_id}/copy")
def add_to_my_repertoires(rep_id: int, body: CopyRequest | None = None, user: User = Depends(current_user),
                          session: Session = Depends(get_session)) -> dict:
    src = session.get(Repertoire, rep_id)
    if src is None or not src.is_library:
        raise HTTPException(404, "library repertoire not found")
    rep = copy_repertoire(session, rep_id, user.id, (body.name if body else None) or src.name)
    return _rep_summary(rep)


# --- Analysis, leaks, deviations -----------------------------------------------------------


@router.post("/analyze")
def analyze(body: AnalyzeRequest, depth: int | None = Query(None, ge=6, le=22),
            user: User = Depends(current_user), session: Session = Depends(get_session)) -> dict:
    if not (user.lichess_username or user.chesscom_username):
        raise HTTPException(422, "Link a Lichess or Chess.com username in your profile first")
    return pipeline.run_analysis(session, user.id, max_games=body.max_games, depth=depth).__dict__


@router.get("/leaks")
def get_leaks(user: User = Depends(current_user), session: Session = Depends(get_session)) -> list[dict]:
    out = []
    for lk in session.scalars(select(Leak).where(Leak.user_id == user.id)):
        out.append({"id": lk.id, "opening": lk.opening_name, "eco": lk.opening_eco, "color": lk.color,
                    "kind": lk.kind, "fen": lk.fen_before, "played": lk.played_move,
                    "played_san": uci_to_san(lk.fen_before, lk.played_move), "theory_move": lk.theory_move,
                    "theory_san": uci_to_san(lk.fen_before, lk.theory_move) if lk.theory_move else None,
                    "eval_loss_cp": lk.eval_loss_cp, "frequency": lk.frequency, "status": lk.status,
                    "gambit_id": lk.gambit_id})
    return sorted(out, key=lambda x: (x["kind"] == "gambit_note", -x["frequency"] * max(x["eval_loss_cp"], 1)))


@router.get("/report")
def get_report(top: int = 8, mode: str = "full", depth: int | None = Query(None, ge=6, le=22),
               user: User = Depends(current_user), session: Session = Depends(get_session)) -> dict:
    if mode not in ("full", "template"):
        raise HTTPException(422, "only verified modes (full, template) are served to users")
    leaks = pipeline.stored_leaks(session, user.id)
    return report.build_gap_report(leaks, mode=mode, depth=depth, rating=user.rating, top=top).model_dump(mode="json")


@router.get("/deviations")
def list_deviations(repertoire_id: int, sort: str = "games", user: User = Depends(current_user),
                    session: Session = Depends(get_session)) -> list[dict]:
    rep = _readable_rep(session, repertoire_id, user)
    devs = deviations.load_deviations(session, repertoire_id, rep.color, sort=sort)
    return [d.model_dump(mode="json") for d in devs]


@router.get("/deviations/{dev_id}")
def deviation_detail(dev_id: int, user: User = Depends(current_user), session: Session = Depends(get_session)
                     ) -> dict:
    row = session.get(RepertoireDeviation, dev_id)
    if row is None:
        raise HTTPException(404, "deviation not found")
    rep = _readable_rep(session, row.repertoire_id, user)
    dev = next(d for d in deviations.load_deviations(session, rep.id, rep.color) if d.id == dev_id)
    fen = board_from_key(dev.node_fen).fen()
    board = chess.Board(fen)
    opening = classify([m.uci() for m in board.move_stack]) if board.move_stack else None
    expl, docs, by = report.explain_deviation(dev, opening.name if opening else rep.name,
                                              opening.eco if opening else None, user.rating)
    stats = masters.master_moves(fen)
    return {**dev.model_dump(mode="json"), "fen": fen, "repertoire_name": rep.name,
            "explanation": expl.explanation, "plan": expl.plan, "memory_aid": expl.memory_aid,
            "citations": [d.citation.model_dump() for d in docs if d.id in expl.citations],
            "generated_by": by, "master_stats": stats.model_dump(mode="json")}


@router.get("/uncovered")
def uncovered(repertoire_id: int, user: User = Depends(current_user), session: Session = Depends(get_session)
              ) -> list[dict]:
    _readable_rep(session, repertoire_id, user)
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
              depth: int | None = Query(None, ge=6, le=22), user: User = Depends(current_user)) -> dict:
    try:
        chess.Board(fen)
    except ValueError:
        raise HTTPException(422, "invalid FEN")
    return recommend_move(fen, side, gambit_id=gambit_id, depth=depth).model_dump(mode="json")


@router.get("/masters")
def master_stats(fen: str) -> dict:
    try:
        chess.Board(fen)
    except ValueError:
        raise HTTPException(422, "invalid FEN")
    return masters.master_moves(fen).model_dump(mode="json")


# --- Scouting and briefing ------------------------------------------------------------------


@router.post("/scout")
def scout_opponent(body: ScoutRequest, depth: int | None = Query(None, ge=6, le=22),
                   user: User = Depends(current_user), session: Session = Depends(get_session)) -> dict:
    briefing, bid = prepare(session, user.id, body.opponent, body.platform, depth=depth, max_games=body.max_games)
    return {"briefing_id": bid, **briefing.model_dump(mode="json")}


def _own_briefing(session: Session, briefing_id: int, user: User) -> BriefingRow:
    row = session.get(BriefingRow, briefing_id)
    if row is None or (row.user_id != user.id and user.role != "admin"):
        raise HTTPException(404, "briefing not found")
    return row


@router.get("/briefing/{briefing_id}")
def get_briefing(briefing_id: int, user: User = Depends(current_user), session: Session = Depends(get_session)
                 ) -> dict:
    row = _own_briefing(session, briefing_id, user)
    return {"briefing_id": row.id, "created_at": row.created_at.isoformat(), **row.content_json}


@router.get("/briefing/{briefing_id}/ics", response_class=PlainTextResponse)
def get_briefing_ics(briefing_id: int, game_time: datetime, user: User = Depends(current_user),
                     session: Session = Depends(get_session)) -> str:
    row = _own_briefing(session, briefing_id, user)
    return briefing_ics(row.opponent, briefing_id, game_time)


# --- Training ---------------------------------------------------------------------------------


@router.post("/quiz/generate")
def generate_quizzes(depth: int | None = Query(None, ge=6, le=22), user: User = Depends(current_user),
                     session: Session = Depends(get_session)) -> dict:
    return {"trail": agent.daily_training(session, user.id, depth=depth).trail}


@router.get("/quiz/next")
def next_quiz(user: User = Depends(current_user), session: Session = Depends(get_session)) -> dict:
    due = srs.get_due(session, user.id, limit=1)
    if not due:
        return {"quiz": None}
    q = due[0]
    return {"quiz": {"id": q.id, "fen": q.fen, "question": q.question, "gambit_id": q.gambit_id}}


@router.post("/quiz/{quiz_id}/answer")
def answer_quiz(quiz_id: int, body: QuizAnswer, user: User = Depends(current_user),
                session: Session = Depends(get_session)) -> dict:
    q = session.get(Quiz, quiz_id)
    if q is None or not session.scalars(select(Review).where(Review.quiz_id == quiz_id,
                                                             Review.user_id == user.id)).first():
        raise HTTPException(404, "quiz not found")
    correct = quiz.check_answer(q, body.move_uci)
    review = srs.grade_review(session, quiz_id, user.id, 5 if correct else 1)
    return {"correct": correct, "correct_move": q.correct_move_uci,
            "correct_san": uci_to_san(q.fen, q.correct_move_uci), "accepted": q.accepted_moves_json,
            "explanation": q.explanation, "next_due": review.due_at.isoformat(), "interval_days": review.interval_days}


@router.get("/progress")
def progress(user: User = Depends(current_user), session: Session = Depends(get_session)) -> dict:
    leaks = session.scalars(select(Leak).where(Leak.user_id == user.id)).all()
    reviews = session.scalars(select(Review).where(Review.user_id == user.id)).all()
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
    return {"stockfish": engine.is_available(), "llm": s.llm_enabled, "provider": s.llm_provider,
            "offline": s.offline, "app": "SecondMind"}
