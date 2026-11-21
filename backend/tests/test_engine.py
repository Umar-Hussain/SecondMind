"""Phase 5: Stockfish wrapper (requires the binary; skipped otherwise)."""

import asyncio

import chess
import pytest

from app.tools import engine

pytestmark = pytest.mark.usefixtures("require_engine")

START = chess.STARTING_FEN
# 1.e4 e5 2.Qh5 Nc6 3.Bc4 Nf6?? 4.Qxf7# — but before mate, White can hang the queen with Qxe5+?
QUEEN_HANG_FEN = "r1bqkbnr/pppp1ppp/2n5/4p2Q/4P3/8/PPPP1PPP/RNB1KBNR w KQkq - 2 3"


def test_start_position_is_near_zero() -> None:
    res = engine.evaluate(START, depth=12)
    assert abs(res.cp_white) < 60
    assert res.best_move_uci is not None


def test_hanging_queen_is_a_large_loss() -> None:
    # 3.Qxf7+?? Kxf7 drops the queen for a pawn.
    loss = engine.eval_loss(QUEEN_HANG_FEN, "h5f7", depth=12)
    assert loss > 500


def test_best_move_has_zero_loss() -> None:
    best = engine.evaluate(START, depth=10).best_move_uci
    assert engine.eval_loss(START, best, depth=10) == 0


def test_restricted_analysis_only_searches_allowed_moves() -> None:
    res = engine.evaluate_restricted(START, ["a2a3", "h2h3"], depth=10)
    assert {line.move_uci for line in res.lines} <= {"a2a3", "h2h3"}


def test_perspective_helpers() -> None:
    assert engine.cp_for(120, "white") == 120
    assert engine.cp_for(120, "black") == -120


def test_cache_returns_same_object() -> None:
    a = engine.evaluate(START, depth=8)
    b = engine.evaluate(START, depth=8)
    assert a == b


def test_analysis_stream_yields_updates() -> None:
    async def collect() -> list[dict]:
        out = []
        async for update in engine.analysis_stream(START, multipv=3, max_depth=8, min_interval=0):
            out.append(update)
        return out

    updates = asyncio.run(collect())
    assert updates
    assert len(updates[-1]["lines"]) == 3
    assert updates[-1]["lines"][0]["san_pv"]
