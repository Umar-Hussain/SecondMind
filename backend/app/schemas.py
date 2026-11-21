"""Pydantic v2 schemas shared by the API, the tools and the LLM layer.

Two families live here:

* **Tool / API schemas** (``NormalizedGame``, ``EngineEval`` ...) describe facts
  produced by deterministic code.
* **LLM structured-output schemas** (``GapReport``, ``Briefing``, ``Quiz`` ...,
  spec 9.3) describe what the model must return. ``generate_structured`` in
  ``llm/client.py`` validates every model response against one of these.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Color = Literal["white", "black"]
Source = Literal["lichess", "chesscom"]
GameResult = Literal["win", "draw", "loss"]


# ---------------------------------------------------------------------------
# Games
# ---------------------------------------------------------------------------


class NormalizedGame(BaseModel):
    """One game from either platform in a single common format."""

    source: Source
    external_id: str
    pgn: str
    color: Color  # the player's color in this game
    result: GameResult  # from the player's point of view
    opponent: str
    opponent_rating: int | None = None
    time_control: str | None = None
    played_at: datetime | None = None
    moves_uci: list[str]
    clocks: list[float] | None = None  # seconds left after each ply, if known
    url: str | None = None
    white: str = ""
    black: str = ""


# ---------------------------------------------------------------------------
# Engine and openings
# ---------------------------------------------------------------------------


class EngineLine(BaseModel):
    move_uci: str
    cp: int  # centipawns from the side-to-move's perspective (mate mapped to +-10000)
    mate: int | None = None
    pv_uci: list[str] = Field(default_factory=list)
    pv_san: list[str] = Field(default_factory=list)


class EngineEval(BaseModel):
    """Stockfish result. ``cp_white`` is from White's perspective (for the bar)."""

    fen: str
    depth: int
    cp_white: int
    cp_stm: int  # side to move
    mate: int | None = None
    best_move_uci: str | None = None
    lines: list[EngineLine] = Field(default_factory=list)


class OpeningInfo(BaseModel):
    eco: str
    name: str
    ply_last_known: int


class MasterMove(BaseModel):
    uci: str
    san: str
    games: int
    white: int = 0
    draws: int = 0
    black: int = 0

    @property
    def score_for_white(self) -> float:
        return (self.white + 0.5 * self.draws) / self.games if self.games else 0.0


class MasterStats(BaseModel):
    fen: str
    total_games: int
    moves: list[MasterMove]
    source: str = "local"


# ---------------------------------------------------------------------------
# Recommender and verification
# ---------------------------------------------------------------------------


class MoveRecommendationOut(BaseModel):
    fen: str
    side: Color
    chosen_uci: str
    chosen_san: str
    chosen_source: Literal["master", "engine", "repertoire"]
    chosen_cp: int | None
    engine_best_uci: str | None
    engine_best_cp: int | None
    reason: str
    rejected: list[dict] = Field(default_factory=list)
    master_moves: list[MasterMove] = Field(default_factory=list)
    gambit_id: str | None = None
    verified: bool = False


class VerificationResult(BaseModel):
    ok: bool
    reasons: list[str] = Field(default_factory=list)
    corrected: str | None = None


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


class Citation(BaseModel):
    id: str
    title: str
    source: str
    url: str | None = None
    year: int | None = None
    players: str | None = None


class RetrievedDoc(BaseModel):
    id: str
    text: str
    score: float
    citation: Citation
    eco: str | None = None
    opening: str | None = None


# ---------------------------------------------------------------------------
# LLM structured outputs (spec 9.3)
# ---------------------------------------------------------------------------


class LeakExplanation(BaseModel):
    """What the LLM returns for a single leak; moves are NOT chosen by the LLM."""

    model_config = ConfigDict(extra="ignore")

    reasoning: str = Field(default="", description="Short reasoning before the answer.")
    explanation: str = Field(description="Why the played move fails, in plain language.")
    plan: str = Field(description="The plan behind the recommended move.")
    memory_aid: str = Field(default="", description="One-line mnemonic.")
    citations: list[str] = Field(default_factory=list, description="Ids of retrieved docs used.")


class GapReportItem(BaseModel):
    opening: str
    color: Color
    kind: str
    position_fen: str
    played: str
    played_san: str = ""
    recommended: str | None
    recommended_san: str = ""
    recommended_source: Literal["master", "engine", "repertoire"] | None = None
    reason: str = ""
    eval_loss: float
    frequency: int = 1
    explanation: str = ""
    plan: str = ""
    memory_aid: str = ""
    master_games: list[Citation] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    verified: bool = False
    is_gambit_note: bool = False


class GapReport(BaseModel):
    leaks: list[GapReportItem]
    generated_by: Literal["llm", "template"] = "template"


class RepertoireDeviationOut(BaseModel):
    id: int | None = None
    repertoire_id: int
    node_fen: str
    color: Color
    played_move: str
    played_san: str = ""
    repertoire_move: str | None
    repertoire_san: str = ""
    recommended_move: str | None = None
    recommended_san: str = ""
    recommended_source: Literal["repertoire", "master", "engine"] | None = None
    reason: str = ""
    # mistake > 80 cp, inaccuracy 31-80 cp, harmless <= 30 cp, better = beats the repertoire move by > 30 cp
    classification: Literal["mistake", "inaccuracy", "harmless", "better", "repertoire_issue", "unjudged"]
    repertoire_issue: bool = False  # the repertoire move itself is > 50 cp worse than the engine best
    played_cp: int | None = None  # player's POV
    repertoire_cp: int | None = None
    best_cp: int | None = None
    is_gambit: bool = False
    status: str = "open"
    game_ids: list[str] = Field(default_factory=list)
    games_count: int
    results: dict[str, int]
    avg_eval_loss: float
    game_links: list[str] = Field(default_factory=list)
    explanation: str = ""
    plan: str = ""
    citations: list[Citation] = Field(default_factory=list)


class UncoveredLineOut(BaseModel):
    id: int | None = None
    repertoire_id: int
    node_fen: str
    opponent_move: str
    opponent_san: str = ""
    games_count: int
    suggested_reply: str | None = None
    citations: list[Citation] = Field(default_factory=list)


class ExtraLine(BaseModel):
    moves: list[str]
    moves_san: list[str] = Field(default_factory=list)
    start_fen: str = ""
    goal: str
    final_eval_cp: int
    study_minutes: int
    master_games: list[Citation] = Field(default_factory=list)
    in_repertoire: bool = False
    explanation: str = ""


class Briefing(BaseModel):
    opponent: str
    likely_openings: list[dict]
    recommended_replies: list[dict]
    extra_lines: list[ExtraLine]
    key_ideas: list[str]
    risks: list[str]
    novelty: dict | None = None
    citations: list[Citation] = Field(default_factory=list)


class QuizOut(BaseModel):
    id: int | None = None
    fen: str
    question: str
    correct_move_uci: str
    accepted_moves: list[str]
    explanation: str = ""
    gambit_id: str | None = None


class ReviewOut(BaseModel):
    prepared_line: list[str]
    first_deviation: dict | None
    swing_ply: int | None
    explanation: str
    leaks_updated: list[int] = Field(default_factory=list)
    new_quizzes: list[int] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# API request bodies
# ---------------------------------------------------------------------------


class UserCreate(BaseModel):
    lichess_username: str | None = None
    chesscom_username: str | None = None
    rating: int | None = None


class AccountLink(BaseModel):
    user_id: int
    platform: Source
    username: str


class RepertoireCreate(BaseModel):
    user_id: int
    name: str
    color: Color
    pgn: str | None = None
    moves_text: str | None = None
    study_url: str | None = None
    intentional_gambit: bool = False


class AnalyzeRequest(BaseModel):
    user_id: int
    max_games: int = 200
    use_llm: bool = True


class ScoutRequest(BaseModel):
    user_id: int
    opponent: str
    platform: Source = "lichess"
    max_games: int = 300


class QuizAnswer(BaseModel):
    user_id: int
    move_uci: str


class ChatRequest(BaseModel):
    user_id: int
    message: str
    session_id: int | None = None
