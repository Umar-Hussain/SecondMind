"""Move symbols, the split-screen comparison and the background analysis job."""

import time

import chess
import pytest

from app.config import FIXTURES_DIR
from app.models import User
from app.schemas import NormalizedGame
from app.services import analysis_jobs
from app.services.compare import compare, games_continuation, tree_line
from app.tools.annotate import annotate, is_sacrifice, kind_for_loss
from app.tools.games import store_games
from app.tools.pgn_utils import fen_key, san_line_to_uci
from app.tools.repertoire import import_pgn, save_tree

START = chess.STARTING_FEN


def _after(moves: str) -> str:
    b = chess.Board()
    for u in san_line_to_uci(moves):
        b.push_uci(u)
    return b.fen()


def test_loss_thresholds() -> None:
    assert [kind_for_loss(x) for x in (0, 25, 50, 100, 200, 400)] == [
        "best", "excellent", "good", "inaccuracy", "mistake", "blunder"]


def test_sacrifice_detection() -> None:
    # Bxf7+ in the Italian gives up the bishop (the king takes it).
    b = chess.Board(_after("e4 e5 Nf3 Nc6 Bc4 Nf6"))
    assert is_sacrifice(b, chess.Move.from_uci("c4f7"))
    assert not is_sacrifice(b, chess.Move.from_uci("e1g1"))  # castling gives nothing away


def test_continuations_follow_tree_and_games() -> None:
    tree = import_pgn((FIXTURES_DIR / "repertoire_white.pgn").read_text(), "white", "e4")
    line = tree_line(tree, chess.Board(_after("e4 e5 Nf3 Nc6 Bb5")))
    assert line[0] == "a7a6"  # the prepared reply comes first
    games = [NormalizedGame(source="lichess", external_id=str(i), pgn="", color="white", result="draw",
                            opponent="o", moves_uci=san_line_to_uci(m)) for i, m in enumerate(
        ["e4 e5 Nf3 Nc6 Bc4 Bc5 c3", "e4 e5 Nf3 Nc6 Bc4 Bc5 O-O", "e4 e5 Nf3 Nc6 Bc4 Bc5 c3 Nf6"])]
    cont, n = games_continuation(games, fen_key(chess.Board(_after("e4 e5 Nf3 Nc6"))), "f1c4")
    assert n == 3 and cont[:2] == ["f8c5", "c2c3"]  # majority move at each ply


def test_annotate_and_compare(db, require_engine) -> None:
    a = annotate(_after("e4 e5"), "d1h5", depth=10)
    assert a["kind"] in ("good", "inaccuracy", "mistake") and a["symbol"]
    assert annotate(START, "e2e4", depth=10, book=True)["kind"] == "book"

    user = User(username="cmp_user", lichess_username="x")
    db.add(user)
    db.commit()
    rep = save_tree(db, user.id, import_pgn((FIXTURES_DIR / "repertoire_white.pgn").read_text(), "white", "e4"), "pgn")
    store_games(db, user.id, [NormalizedGame(source="lichess", external_id="1", pgn="", color="white", result="loss",
                                             opponent="o", moves_uci=san_line_to_uci("e4 e5 Nf3 Nc6 Bc4 Bc5 c3"))])
    out = compare(db, user.id, rep.id, _after("e4 e5 Nf3 Nc6"), "f1c4", depth=10)
    assert out["you"]["san"] == "Bc4" and out["you"]["games"] == 1
    assert [m["san"] for m in out["you"]["line"]][:2] == ["Bc5", "c3"]
    assert out["repertoire"]["san"] == "Bb5" and out["repertoire"]["line"][0]["san"] == "a6"
    assert out["suggestion"]["line"]  # Stockfish's continuation


def test_background_job_reports_progress(monkeypatch) -> None:
    def fake_run(session, user_id, max_games=200, depth=None, progress=None):
        for i in range(1, 4):
            progress("games", i, 3)
        from app.services.pipeline import AnalysisSummary
        return AnalysisSummary(user_id=user_id, games_fetched=3)

    monkeypatch.setattr(analysis_jobs.pipeline, "run_analysis", fake_run)
    first = analysis_jobs.start(987654)
    assert first["state"] == "running"
    for _ in range(50):
        st = analysis_jobs.status(987654)
        if st["state"] != "running":
            break
        time.sleep(0.02)
    assert st["state"] == "done" and st["percent"] == 100 and st["summary"]["games_fetched"] == 3
