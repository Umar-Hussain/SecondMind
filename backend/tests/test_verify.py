"""verification guard — legal, illegal, engine-refuted and fake-citation cases."""

import chess
import pytest

from app.schemas import Citation, RetrievedDoc
from app.tools import verify

START = chess.STARTING_FEN
QUEEN_HANG_FEN = "r1bqkbnr/pppp1ppp/2n5/4p2Q/4P3/8/PPPP1PPP/RNB1KBNR w KQkq - 2 3"


def _doc(i: str) -> RetrievedDoc:
    return RetrievedDoc(id=i, text="", score=1, citation=Citation(id=i, title=i, source="s"))


def test_legal_and_illegal_moves() -> None:
    assert verify.is_legal(START, "e4")
    assert verify.is_legal(START, "g1f3")
    assert not verify.is_legal(START, "e5")
    assert not verify.is_legal(START, "Ke2")


def test_verify_line() -> None:
    ok = verify.verify_line(START, ["e4", "c5", "Nf3"])
    assert ok.ok and ok.corrected
    bad = verify.verify_line(START, ["e4", "c5", "Nf6"])
    assert not bad.ok and "move 3" in bad.reasons[0]


@pytest.mark.usefixtures("require_engine")
def test_engine_refuted_recommendation() -> None:
    assert verify.verify_recommendation(START, "e4", depth=10).ok
    refuted = verify.verify_recommendation(QUEEN_HANG_FEN, "Qxf7+", depth=10)
    assert not refuted.ok and "loses" in refuted.reasons[0]


def test_illegal_recommendation_fails_without_engine() -> None:
    assert not verify.verify_recommendation(START, "Qh5").ok


def test_fake_citation_is_rejected() -> None:
    docs = [_doc("idea-englund"), _doc("game-001-C33")]
    assert verify.verify_citations("See [idea-englund] and [game-001-C33].", docs).ok
    bad = verify.verify_citations("As shown in [idea-made-up].", docs)
    assert not bad.ok and "idea-made-up" in bad.reasons[0]
    assert not verify.verify_citations(["idea-nope"], docs).ok


def test_text_moves_must_come_from_tools() -> None:
    allowed = verify.allowed_line(START, ["e2e4", "c7c5", "g1f3"])
    assert verify.verify_text_moves("After 1.e4 c5 2.Nf3 White develops.", allowed).ok
    bad = verify.verify_text_moves("Play 2.Nc3 or even Qh5+!", allowed)
    assert not bad.ok
    assert any("Nc3" in r for r in bad.reasons) and any("Qh5" in r for r in bad.reasons)


def test_extract_moves_handles_castling_and_promotion() -> None:
    assert set(verify.extract_moves("O-O then e8=Q+ and Rxd7#")) >= {"O-O", "e8=Q", "Rxd7"}
