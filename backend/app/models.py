"""SQLAlchemy tables.

JSON payloads (lists of moves, result counts, citations) are stored in ``*_json``
text columns using SQLAlchemy's JSON type, which maps to TEXT on SQLite and to
JSONB-compatible JSON on Postgres.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Users and games
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Login. Usernames are stored lower-case; passwords only as salted PBKDF2 hashes.
    username: Mapped[str | None] = mapped_column(String(32), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(10), default="user")  # user | admin
    display_name: Mapped[str | None] = mapped_column(String(64))
    lichess_username: Mapped[str | None] = mapped_column(String(64))
    chesscom_username: Mapped[str | None] = mapped_column(String(64))
    rating: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Game(Base):
    """A normalized game from Lichess or Chess.com, tagged with its source."""

    __tablename__ = "games"
    # Per user: both players of one game may use the app and each store their own copy.
    __table_args__ = (UniqueConstraint("user_id", "source", "external_id", name="uq_game_user_source_ext"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    source: Mapped[str] = mapped_column(String(16))  # "lichess" | "chesscom"
    external_id: Mapped[str] = mapped_column(String(128))
    pgn: Mapped[str] = mapped_column(Text)
    color: Mapped[str] = mapped_column(String(5))  # player's color
    result: Mapped[str] = mapped_column(String(5))  # "win" | "draw" | "loss" (player POV)
    opponent: Mapped[str] = mapped_column(String(64))
    opponent_rating: Mapped[int | None] = mapped_column(Integer)
    time_control: Mapped[str | None] = mapped_column(String(32))
    played_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    moves_uci: Mapped[list] = mapped_column(JSON, default=list)
    clocks: Mapped[list | None] = mapped_column(JSON)
    url: Mapped[str | None] = mapped_column(String(256))


# ---------------------------------------------------------------------------
# Repertoire
# ---------------------------------------------------------------------------


class Repertoire(Base):
    __tablename__ = "repertoires"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(128))
    color: Mapped[str] = mapped_column(String(5))
    source_type: Mapped[str] = mapped_column(String(16))  # pgn | study | text | generated
    raw_pgn: Mapped[str] = mapped_column(Text, default="")
    intentional_gambit: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | draft
    # Library repertoires are published by an admin; every user can view and copy them.
    is_library: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str] = mapped_column(Text, default="")
    copied_from_id: Mapped[int | None] = mapped_column(Integer)  # library repertoire it was copied from
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class RepertoireNode(Base):
    """One position in a repertoire tree, keyed by normalized FEN (transpositions merge)."""

    __tablename__ = "repertoire_nodes"
    __table_args__ = (UniqueConstraint("repertoire_id", "fen_key", name="uq_node_pos"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    repertoire_id: Mapped[int] = mapped_column(ForeignKey("repertoires.id"))
    fen_key: Mapped[str] = mapped_column(String(100))
    user_move_uci: Mapped[str | None] = mapped_column(String(8))
    alternative_moves_json: Mapped[list] = mapped_column(JSON, default=list)
    opponent_moves_json: Mapped[list] = mapped_column(JSON, default=list)
    comment: Mapped[str] = mapped_column(Text, default="")
    parent_fen_key: Mapped[str | None] = mapped_column(String(100))


class RepertoireDeviation(Base):
    __tablename__ = "repertoire_deviations"

    id: Mapped[int] = mapped_column(primary_key=True)
    repertoire_id: Mapped[int] = mapped_column(ForeignKey("repertoires.id"))
    node_fen_key: Mapped[str] = mapped_column(String(100))
    played_move: Mapped[str] = mapped_column(String(8))
    repertoire_move: Mapped[str | None] = mapped_column(String(8))
    recommended_move: Mapped[str | None] = mapped_column(String(8))
    recommended_source: Mapped[str | None] = mapped_column(String(16))
    classification: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(Text, default="")
    games_count: Mapped[int] = mapped_column(Integer, default=0)
    results_json: Mapped[dict] = mapped_column(JSON, default=dict)
    avg_eval_loss: Mapped[float] = mapped_column(Float, default=0.0)
    game_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="open")


class UncoveredLine(Base):
    __tablename__ = "uncovered_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    repertoire_id: Mapped[int] = mapped_column(ForeignKey("repertoires.id"))
    node_fen_key: Mapped[str] = mapped_column(String(100))
    opponent_move: Mapped[str] = mapped_column(String(8))
    games_count: Mapped[int] = mapped_column(Integer, default=0)
    suggested_reply: Mapped[str | None] = mapped_column(String(8))


# ---------------------------------------------------------------------------
# Leaks, gambits, theory
# ---------------------------------------------------------------------------


class Leak(Base):
    """A repeated (position, move) pair that costs the player evaluation or results."""

    __tablename__ = "leaks"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    opening_eco: Mapped[str | None] = mapped_column(String(4))
    opening_name: Mapped[str | None] = mapped_column(String(128))
    color: Mapped[str] = mapped_column(String(5))
    ply: Mapped[int] = mapped_column(Integer)
    fen_before: Mapped[str] = mapped_column(String(100))
    played_move: Mapped[str] = mapped_column(String(8))
    theory_move: Mapped[str | None] = mapped_column(String(8))
    eval_loss_cp: Mapped[float] = mapped_column(Float, default=0.0)
    frequency: Mapped[int] = mapped_column(Integer, default=1)
    games_count: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="open")
    # deviation | mistake | gambit_deviation | defender_trap | gambit_note
    kind: Mapped[str] = mapped_column(String(20), default="mistake")
    gambit_id: Mapped[str | None] = mapped_column(String(64))
    game_ids_json: Mapped[list] = mapped_column(JSON, default=list)


class Gambit(Base):
    __tablename__ = "gambits"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    eco: Mapped[str | None] = mapped_column(String(4))
    side: Mapped[str] = mapped_column(String(5))
    trigger_moves_uci: Mapped[list] = mapped_column(JSON, default=list)
    theory_end_ply: Mapped[int] = mapped_column(Integer, default=12)
    objective_eval_cp: Mapped[int] = mapped_column(Integer, default=0)
    soundness: Mapped[str] = mapped_column(String(24), default="playable")
    notes: Mapped[str] = mapped_column(Text, default="")


class TheoryDoc(Base):
    __tablename__ = "theory_docs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source: Mapped[str] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(256))
    eco: Mapped[str | None] = mapped_column(String(4))
    text: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


# ---------------------------------------------------------------------------
# Scouting and preparation
# ---------------------------------------------------------------------------


class OpponentProfile(Base):
    __tablename__ = "opponent_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    lichess_username: Mapped[str] = mapped_column(String(64))
    platform: Mapped[str] = mapped_column(String(16), default="lichess")
    white_repertoire_json: Mapped[list] = mapped_column(JSON, default=list)
    black_repertoire_json: Mapped[list] = mapped_column(JSON, default=list)
    weaknesses_json: Mapped[list] = mapped_column(JSON, default=list)
    games_analyzed: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SavedReport(Base):
    """The user's latest gap report, built in the background after each analysis."""

    __tablename__ = "saved_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    content_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Briefing(Base):
    __tablename__ = "briefings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    opponent: Mapped[str] = mapped_column(String(64))
    content_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PrepLine(Base):
    __tablename__ = "prep_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    briefing_id: Mapped[int | None] = mapped_column(ForeignKey("briefings.id"))
    opponent_line_fen: Mapped[str] = mapped_column(String(100))
    moves_uci: Mapped[list] = mapped_column(JSON, default=list)
    goal: Mapped[str] = mapped_column(Text, default="")
    eval_cp: Mapped[int] = mapped_column(Integer, default=0)
    master_games_json: Mapped[list] = mapped_column(JSON, default=list)
    study_minutes: Mapped[int] = mapped_column(Integer, default=5)
    in_repertoire: Mapped[bool] = mapped_column(Boolean, default=False)


class MoveRecommendation(Base):
    __tablename__ = "move_recommendations"

    id: Mapped[int] = mapped_column(primary_key=True)
    fen: Mapped[str] = mapped_column(String(100))
    side: Mapped[str] = mapped_column(String(5))
    master_moves_json: Mapped[list] = mapped_column(JSON, default=list)
    engine_best_uci: Mapped[str | None] = mapped_column(String(8))
    engine_best_cp: Mapped[int | None] = mapped_column(Integer)
    chosen_uci: Mapped[str] = mapped_column(String(8))
    chosen_source: Mapped[str] = mapped_column(String(16))  # master | engine | repertoire
    chosen_cp: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text, default="")
    gambit_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------


class Quiz(Base):
    __tablename__ = "quizzes"
    __table_args__ = (UniqueConstraint("fen", "correct_move_uci", name="uq_quiz_pos"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    leak_id: Mapped[int | None] = mapped_column(ForeignKey("leaks.id"))
    fen: Mapped[str] = mapped_column(String(100))
    question: Mapped[str] = mapped_column(Text)
    correct_move_uci: Mapped[str] = mapped_column(String(8))
    accepted_moves_json: Mapped[list] = mapped_column(JSON, default=list)
    explanation: Mapped[str] = mapped_column(Text, default="")
    engine_eval_cp: Mapped[int | None] = mapped_column(Integer)
    gambit_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Review(Base):
    """SM-2 scheduling state for one quiz and one user."""

    __tablename__ = "reviews"
    __table_args__ = (UniqueConstraint("quiz_id", "user_id", name="uq_review"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    ease: Mapped[float] = mapped_column(Float, default=2.5)
    interval_days: Mapped[int] = mapped_column(Integer, default=0)
    repetitions: Mapped[int] = mapped_column(Integer, default=0)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_result: Mapped[int | None] = mapped_column(Integer)


class HintLog(Base):
    __tablename__ = "hint_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    level: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    leaked_answer: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class StudyPlan(Base):
    __tablename__ = "study_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    week_start: Mapped[str] = mapped_column(String(10))
    plan_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# ---------------------------------------------------------------------------
# AI layer: concepts, chat, run logs
# ---------------------------------------------------------------------------


class ConceptCluster(Base):
    __tablename__ = "concept_clusters"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    label: Mapped[str] = mapped_column(Text)
    evidence_json: Mapped[dict] = mapped_column(JSON, default=dict)
    leak_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    example_game_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    supported: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("chat_sessions.id"))
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    tool_calls_json: Mapped[list] = mapped_column(JSON, default=list)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Run(Base):
    """Audit log: every LLM call, tool call and verification result."""

    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))  # llm | tool | verify | job | agent
    name: Mapped[str] = mapped_column(String(64))
    input_json: Mapped[dict] = mapped_column(JSON, default=dict)
    output_json: Mapped[dict] = mapped_column(JSON, default=dict)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class EngineCache(Base):
    """Stockfish results cached by (FEN, depth, multipv, restriction)."""

    __tablename__ = "engine_cache"

    key: Mapped[str] = mapped_column(String(300), primary_key=True)
    result_json: Mapped[dict] = mapped_column(JSON)
