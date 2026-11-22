"""Stockfish wrapper (spec Phase 5).

Responsibilities

* One managed **batch** engine process guarded by a lock, used by leak mining,
  the recommender, deviation judging and verification.
* A **separate** async engine process per live-analysis stream, so the live
  board never blocks batch jobs (spec B5 pitfall).
* Results cached by ``(fen, depth, multipv, restriction)`` in memory and in a
  small SQLite file, because the same opening positions recur constantly.
* Restricted root-move analysis (``root_moves``) for gambit-aware evaluation.

Perspective convention (spec 8.1 step 6 / risks table):

* ``cp_white`` — White's point of view, used only for the evaluation bar.
* ``cp_stm`` and every ``EngineLine.cp`` — side to move's point of view.
* Callers convert to the *player's* point of view with :func:`cp_for`.
"""

from __future__ import annotations

import asyncio
import atexit
import hashlib
import json
import sqlite3
import threading
from collections.abc import AsyncIterator
from pathlib import Path

import chess
import chess.engine

from app.config import DATA_DIR, get_settings
from app.schemas import EngineEval, EngineLine

MATE_CP = 10_000


class EngineUnavailable(RuntimeError):
    """Raised when no Stockfish binary is configured / found."""


# ---------------------------------------------------------------------------
# Persistent cache
# ---------------------------------------------------------------------------


class _Cache:
    """Tiny key-value store: memory dict in front of a SQLite table."""

    def __init__(self, path: Path) -> None:
        self._mem: dict[str, dict] = {}
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute("CREATE TABLE IF NOT EXISTS cache (k TEXT PRIMARY KEY, v TEXT)")
        self._conn.commit()

    def get(self, key: str) -> dict | None:
        if key in self._mem:
            return self._mem[key]
        with self._lock:
            row = self._conn.execute("SELECT v FROM cache WHERE k = ?", (key,)).fetchone()
        if row:
            self._mem[key] = json.loads(row[0])
            return self._mem[key]
        return None

    def put(self, key: str, value: dict) -> None:
        self._mem[key] = value
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO cache VALUES (?, ?)", (key, json.dumps(value)))
            self._conn.commit()


_cache = _Cache(DATA_DIR / "cache" / "engine_cache.sqlite")


def _cache_key(fen: str, depth: int, multipv: int, restrict: list[str] | None) -> str:
    r = ",".join(sorted(restrict)) if restrict else "*"
    raw = f"{fen}|{depth}|{multipv}|{r}"
    return hashlib.sha1(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Batch engine (singleton)
# ---------------------------------------------------------------------------

_engine: chess.engine.SimpleEngine | None = None
_engine_lock = threading.Lock()


def _binary() -> Path:
    path = get_settings().stockfish_abspath
    if not path.exists():
        raise EngineUnavailable(f"Stockfish not found at {path}. Set STOCKFISH_PATH in .env.")
    return path


def _get_engine() -> chess.engine.SimpleEngine:
    """Start the batch engine on first use (caller must hold ``_engine_lock``)."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = chess.engine.SimpleEngine.popen_uci(str(_binary()))
        _engine.configure({"Threads": settings.stockfish_threads, "Hash": settings.stockfish_hash_mb})
    return _engine


def shutdown() -> None:
    """Close the batch engine (registered with atexit and FastAPI shutdown)."""
    global _engine
    with _engine_lock:
        if _engine is not None:
            try:
                _engine.quit()
            except Exception:  # pragma: no cover - best effort on shutdown
                pass
            _engine = None


# python-chess runs SimpleEngine on a non-daemon thread, and Python joins
# non-daemon threads *before* plain atexit handlers run — so an atexit-only
# shutdown never fires and the process hangs on exit. threading's own hook runs
# before that join (concurrent.futures uses the same mechanism).
try:
    threading._register_atexit(shutdown)  # type: ignore[attr-defined]
except (AttributeError, RuntimeError):  # pragma: no cover - very old/new Pythons
    atexit.register(shutdown)


def is_available() -> bool:
    try:
        _binary()
        return True
    except EngineUnavailable:
        return False


def _score_cp(score: chess.engine.PovScore, turn: chess.Color) -> tuple[int, int | None]:
    pov = score.pov(turn)
    return pov.score(mate_score=MATE_CP), pov.mate()


def _analyse(fen: str, depth: int, multipv: int, restrict: list[str] | None) -> EngineEval:
    board = chess.Board(fen)
    if board.is_game_over():
        # Terminal position: mate or draw, no move to search.
        if board.is_checkmate():
            cp = -MATE_CP
            return EngineEval(fen=fen, depth=0, cp_stm=cp, cp_white=cp if board.turn else -cp, mate=0)
        return EngineEval(fen=fen, depth=0, cp_stm=0, cp_white=0)

    root_moves = None
    if restrict:
        root_moves = [m for m in (chess.Move.from_uci(u) for u in restrict) if m in board.legal_moves]
        if not root_moves:
            raise ValueError(f"none of the restricted moves {restrict} is legal in {fen}")
        multipv = min(multipv, len(root_moves))
    else:
        multipv = min(multipv, board.legal_moves.count())

    with _engine_lock:
        infos = _get_engine().analyse(
            board, chess.engine.Limit(depth=depth), multipv=multipv, root_moves=root_moves
        )
    if isinstance(infos, dict):
        infos = [infos]

    lines: list[EngineLine] = []
    for info in infos:
        pv = info.get("pv") or []
        if not pv:
            continue
        cp, mate = _score_cp(info["score"], board.turn)
        pv_uci = [m.uci() for m in pv]
        lines.append(EngineLine(move_uci=pv_uci[0], cp=cp, mate=mate, pv_uci=pv_uci, pv_san=_pv_san(board, pv)))
    lines.sort(key=lambda line: line.cp, reverse=True)
    best = lines[0]
    return EngineEval(
        fen=fen,
        depth=depth,
        cp_stm=best.cp,
        cp_white=best.cp if board.turn == chess.WHITE else -best.cp,
        mate=best.mate,
        best_move_uci=best.move_uci,
        lines=lines,
    )


def _pv_san(board: chess.Board, pv: list[chess.Move]) -> list[str]:
    b = board.copy()
    out = []
    for m in pv:
        if m not in b.legal_moves:
            break
        out.append(b.san(m))
        b.push(m)
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def evaluate(fen: str, depth: int | None = None, multipv: int = 1) -> EngineEval:
    """Evaluate a position (cached). ``cp_white`` for the bar, ``cp_stm`` for logic."""
    depth = depth or get_settings().engine_depth
    key = _cache_key(fen, depth, multipv, None)
    hit = _cache.get(key)
    if hit:
        return EngineEval.model_validate(hit)
    result = _analyse(fen, depth, multipv, None)
    _cache.put(key, result.model_dump())
    return result


def evaluate_restricted(
    fen: str, allowed_moves_uci: list[str], depth: int | None = None, multipv: int | None = None
) -> EngineEval:
    """Analyse only the given root moves (gambit-aware evaluation, spec 8.3)."""
    depth = depth or get_settings().engine_depth
    multipv = multipv or len(allowed_moves_uci)
    key = _cache_key(fen, depth, multipv, allowed_moves_uci)
    hit = _cache.get(key)
    if hit:
        return EngineEval.model_validate(hit)
    result = _analyse(fen, depth, multipv, allowed_moves_uci)
    _cache.put(key, result.model_dump())
    return result


def evaluate_moves(fen: str, moves_uci: list[str], depth: int | None = None) -> dict[str, int]:
    """Side-to-move centipawns for each listed move, searched together."""
    legal = [u for u in dict.fromkeys(moves_uci) if chess.Move.from_uci(u) in chess.Board(fen).legal_moves]
    if not legal:
        return {}
    res = evaluate_restricted(fen, legal, depth=depth, multipv=len(legal))
    return {line.move_uci: line.cp for line in res.lines}


def eval_loss(fen: str, move_uci: str, depth: int | None = None) -> int:
    """Centipawn loss of ``move_uci`` versus the engine best (>= 0)."""
    best = evaluate(fen, depth=depth)
    if best.best_move_uci == move_uci:
        return 0
    move_cp = evaluate_moves(fen, [move_uci], depth=depth).get(move_uci)
    if move_cp is None:
        raise ValueError(f"illegal move {move_uci} in {fen}")
    return max(0, best.cp_stm - move_cp)


def move_loss(fen: str, move_uci: str, depth: int | None = None) -> tuple[int, str | None]:
    """(centipawn loss of ``move_uci`` vs the best move, best move) with as few searches as possible.

    One multi-PV search usually contains the played move (players mostly pick reasonable
    moves); only when it does not is a second, restricted search needed.
    """
    ev = evaluate(fen, depth=depth, multipv=3)
    cp = next((line.cp for line in ev.lines if line.move_uci == move_uci), None)
    if cp is None:
        cp = evaluate_moves(fen, [move_uci], depth=depth).get(move_uci)
        if cp is None:
            raise ValueError(f"illegal move {move_uci} in {fen}")
    return max(0, ev.cp_stm - cp), ev.best_move_uci


def cp_for(cp_white: int, color: str) -> int:
    """Convert a White-POV evaluation to the given player's POV."""
    return cp_white if color == "white" else -cp_white


# ---------------------------------------------------------------------------
# Live analysis stream (separate process per stream)
# ---------------------------------------------------------------------------


async def analysis_stream(
    fen: str, multipv: int = 3, max_depth: int = 30, min_interval: float = 0.3
) -> AsyncIterator[dict]:
    """Yield live analysis updates for ``fen`` until cancelled or ``max_depth``.

    Each update: ``{depth, cp_white, mate, lines: [{move, san_pv, cp_white}]}``.
    Updates are throttled to at most one every ``min_interval`` seconds per depth.
    The engine process is always closed, also when the consumer cancels.
    """
    board = chess.Board(fen)
    if board.is_game_over():
        yield {"depth": 0, "cp_white": 0, "mate": None, "lines": [], "game_over": True}
        return

    transport, engine = await chess.engine.popen_uci(str(_binary()))
    try:
        await engine.configure({"Threads": 1, "Hash": 64})
        multipv = min(multipv, board.legal_moves.count())
        last_sent, last_depth = 0.0, -1
        loop = asyncio.get_running_loop()
        with await engine.analysis(board, chess.engine.Limit(depth=max_depth), multipv=multipv) as analysis:
            snapshot: dict[int, dict] = {}
            async for info in analysis:
                if "pv" not in info or "score" not in info or "depth" not in info:
                    continue
                idx = info.get("multipv", 1)
                cp_white = info["score"].white().score(mate_score=MATE_CP)
                snapshot[idx] = {
                    "move": info["pv"][0].uci(),
                    "san_pv": _pv_san(board, info["pv"][:10]),
                    "cp_white": cp_white,
                    "mate": info["score"].white().mate(),
                }
                depth = info["depth"]
                now = loop.time()
                if len(snapshot) >= multipv and (depth > last_depth or now - last_sent >= min_interval):
                    if now - last_sent < min_interval and depth == last_depth:
                        continue
                    lines = [snapshot[i] for i in sorted(snapshot)]
                    yield {"depth": depth, "cp_white": lines[0]["cp_white"], "mate": lines[0]["mate"], "lines": lines}
                    last_sent, last_depth = now, depth
    finally:
        try:
            await engine.quit()
        except Exception:  # pragma: no cover
            transport.close()
