"""Phase 9: theory corpus and hybrid retrieval."""

from app.tools.rag import get_index, load_corpus, master_games_for, retrieve


def test_corpus_has_ideas_and_master_games() -> None:
    chunks = load_corpus()
    assert sum(c.id.startswith("idea-") for c in chunks) >= 20
    assert sum(c.id.startswith("game-") for c in chunks) >= 3
    assert all(c.license for c in chunks)


def test_najdorf_query_returns_najdorf_first() -> None:
    hits = retrieve("plan for White in the Najdorf 6.Be3", eco="B90")
    assert hits[0].id == "idea-najdorf-english"
    c = hits[0].citation
    assert c.title and c.source and c.id == hits[0].id


def test_englund_trap_query() -> None:
    hits = retrieve("Englund gambit trap Bc3 Bb4 queen takes b2")
    assert hits[0].id == "idea-englund"


def test_caro_advance_query_without_eco() -> None:
    ids = [h.id for h in retrieve("Caro-Kann Advance bishop f5 c5 break Short system", k=3)]
    assert "idea-caro-advance" in ids


def test_modes_all_work() -> None:
    for mode in ("hybrid", "dense", "bm25"):
        assert retrieve("King's Gambit f-file compensation", mode=mode)


def test_master_games_for_evans() -> None:
    games = master_games_for("C52", "Italian Game: Evans Gambit")
    assert games and "Anderssen" in (games[0].players or "")


def test_index_is_cached() -> None:
    assert get_index() is get_index()
