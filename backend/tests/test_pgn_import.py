"""Real-world PGN exports (Lichess studies, Chess.com, ChessBase) import without fuss."""

import itertools

import chess
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.tools.pgn_utils import fen_key
from app.tools.repertoire import clean_comment, detect_color, import_pgn

BOM = chr(0xFEFF)
STUDY = BOM + """[Event "Dubov Italian: Main line"]
[Site "https://lichess.org/study/abcd1234/efgh5678"]
[Date "2025.08.10"]
[White "Daniil Dubov"]
[Black "Opponent, Some"]
[WhiteElo "2700"]
[Result "*"]
[Variant "Standard"]
[ECO "C54"]
[Opening "Italian Game: Classical Variation, Greco Gambit"]
[StudyName "Daniil Dubov Agressive Italian"]
[ChapterName "Main line"]
[Annotator "https://lichess.org/@/someone"]
[Orientation "white"]

1. e4 { [%clk 0:10:00] [%eval 0.3] Best by test } 1... e5 2. Nf3 Nc6 3. Bc4 { [%cal Gf7f5,Rc4f7] [%csl Rf7] Eyeing f7. } 3... Bc5 4. c3!? Nf6 5. d4 exd4 6. e5 $1 ( 6. cxd4 Bb4+ 7. Bd2 ) 6... d5 *

[Event "Dubov Italian: From a position"]
[Variant "From Position"]
[FEN "r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/2P2N2/PP1P1PPP/RNBQK2R w KQkq - 3 5"]
[SetUp "1"]
[Orientation "white"]

5. d4 exd4 6. cxd4 Bb4+ *

[Event "Chess960 chapter"]
[Variant "Chess960"]
[FEN "bbqnnrkr/pppppppp/8/8/8/8/PPPPPPPP/BBQNNRKR w KQkq - 0 1"]

1. f4 f5 *

[Event "Broken chapter"]
[Orientation "white"]

1. d4 d5 2. c4 Ke3 3. Nc3 *
""".replace("\n", "\r\n")


def _key(moves: str) -> str:
    b = chess.Board()
    for san in moves.split():
        b.push_san(san)
    return fen_key(b)


def test_messy_study_imports_with_everything_kept() -> None:
    tree = import_pgn(STUDY, "white", "Dubov")
    # Main line and its variation are there, despite clocks, evals, arrows, NAGs and player names.
    assert tree.get_user_move(_key("e4 e5 Nf3 Nc6 Bc4 Bc5 c3 Nf6 d4 exd4")) == "e4e5"
    assert "f1d2" not in (tree.nodes[_key("e4 e5 Nf3 Nc6 Bc4 Bc5 c3 Nf6 d4 exd4")].alternatives or [])
    assert tree.nodes[_key("e4 e5 Nf3 Nc6 Bc4 Bc5 c3 Nf6 d4 exd4")].alternatives == ["c3d4"]
    # Arrow / clock / eval commands are stripped from comments, the human text stays.
    assert tree.nodes[_key("e4 e5 Nf3 Nc6")].comment == "Eyeing f7."
    # The chapter that starts from a set-up position is imported too.
    custom = chess.Board("r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/2P2N2/PP1P1PPP/RNBQK2R w KQkq - 3 5")
    assert tree.get_user_move(fen_key(custom)) == "d2d4"
    # The Chess960 chapter is skipped with a warning; the broken chapter keeps its legal moves.
    assert any("Chess960" in i.message for i in tree.issues)
    assert tree.get_user_move(_key("d4 d5")) == "c2c4"
    assert any("Ke3" in i.message and "move 2 (Black)" in i.location for i in tree.errors)


def test_clean_comment() -> None:
    assert clean_comment("[%clk 0:03:00] [%eval #-3] Good  move [%cal Ge2e4]") == "Good move"
    assert clean_comment("") == ""


def test_detect_color() -> None:
    assert detect_color(STUDY) == "white"
    assert detect_color(STUDY.replace('[Orientation "white"]', '[Orientation "black"]')) == "black"
    black_pgn = '[Event "x"]\n\n1. e4 c6 2. d4 (2. Nc3 d5) 2... d5 *\n\n[Event "y"]\n\n1. d4 d5 *'
    assert detect_color(black_pgn) == "black"


_ids = itertools.count(1)


@pytest.fixture(scope="module")
def api():
    with TestClient(app) as c:
        yield c


def test_upload_saves_despite_problems_and_picks_name_and_colour(api) -> None:
    tok = api.post("/auth/signup", json={"username": f"pgnuser{next(_ids)}", "password": "pgn-pass-123"}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    res = api.post("/repertoires", headers=h, json={"name": "", "color": "auto", "pgn": STUDY}).json()
    assert res["saved"] and res["color"] == "white"
    assert res["name"] == "Daniil Dubov Agressive Italian"          # taken from the study header
    assert any(i["level"] == "error" for i in res["issues"])          # the broken line is reported...
    assert res["nodes"] > 15                                          # ...but everything else is saved
    empty = api.post("/repertoires", headers=h, json={"name": "x", "color": "white", "pgn": "garbage"}).json()
    assert not empty["saved"]
