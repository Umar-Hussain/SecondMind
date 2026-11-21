"""Phase 11: the five recommender cases from the specification."""

import chess
import pytest

from app.schemas import MasterMove, MasterStats
from app.tools.pgn_utils import san_line_to_uci
from app.tools.recommend import _check, recommend_move

pytestmark = pytest.mark.usefixtures("require_engine")
DEPTH = 12
START = chess.STARTING_FEN
QUEEN_HANG_FEN = "r1bqkbnr/pppp1ppp/2n5/4p2Q/4P3/8/PPPP1PPP/RNB1KBNR w KQkq - 2 3"


def _stats(fen: str, *moves: tuple[str, int]) -> MasterStats:
    board = chess.Board(fen)
    ms = [MasterMove(uci=u, san=board.san(chess.Move.from_uci(u)), games=g) for u, g in moves]
    return MasterStats(fen=fen, total_games=sum(g for _, g in moves), moves=ms, source="test")


def _fen_after(moves: str) -> str:
    b = chess.Board()
    for u in san_line_to_uci(moves):
        b.push_uci(u)
    return b.fen()


def test_popular_move_is_sound_master_chosen() -> None:
    rec = recommend_move(START, depth=DEPTH, master_provider=lambda f: _stats(f, ("e2e4", 900), ("d2d4", 800)))
    assert rec.chosen_uci == "e2e4" and rec.chosen_source == "master" and rec.verified


def test_popular_move_loses_advantage_engine_chosen() -> None:
    rec = recommend_move(QUEEN_HANG_FEN, depth=DEPTH,
                         master_provider=lambda f: _stats(f, ("h5f7", 500), ("h5f3", 10)))
    assert rec.chosen_source == "engine"
    assert rec.chosen_uci != "h5f7"
    assert any(r["move"] == "h5f7" for r in rec.rejected)


def test_slightly_worse_popular_move_still_master() -> None:
    # 1.Nf3 is not necessarily Stockfish's first choice but is within 30 cp.
    rec = recommend_move(START, depth=DEPTH, master_provider=lambda f: _stats(f, ("g1f3", 900), ("e2e4", 100)))
    assert rec.chosen_uci == "g1f3" and rec.chosen_source == "master"


def test_no_master_data_engine_chosen() -> None:
    rec = recommend_move(START, depth=DEPTH, master_provider=lambda f: MasterStats(fen=f, total_games=0, moves=[]))
    assert rec.chosen_source == "engine" and "fewer than" in rec.reason


def test_gambit_mode_keeps_the_gambit_move() -> None:
    # Danish: after 3...dxc3 the engine may prefer recapturing with the knight;
    # in gambit mode the recommendation must stay on gambit theory (4.Bc4).
    fen = _fen_after("e4 e5 d4 exd4 c3 dxc3")
    rec = recommend_move(fen, "white", gambit_id="danish_gambit", depth=DEPTH,
                         master_provider=lambda f: _stats(f, ("b1c3", 900), ("f1c4", 300)))
    assert rec.chosen_uci == "f1c4"
    assert rec.gambit_id == "danish_gambit"
    # Asking for the objective best switches gambit mode off.
    objective = recommend_move(fen, "white", gambit_id="danish_gambit", depth=DEPTH, objective=True,
                               master_provider=lambda f: _stats(f, ("b1c3", 900), ("f1c4", 300)))
    assert objective.gambit_id is None


def test_acceptability_conditions() -> None:
    assert _check(20, 0, 30) is None
    assert _check(50, 10, 30) == "lost 40 cp"
    assert _check(120, 95, 30) is None
    assert _check(110, 50, 70) == "gave away the advantage"
    assert _check(40, -5, 50) == "gave away the edge"
