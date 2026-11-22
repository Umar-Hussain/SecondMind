"""Opening overview: the user's games grouped by opening and checked against their repertoires."""

from app.config import FIXTURES_DIR
from app.models import User
from app.schemas import NormalizedGame
from app.services.pipeline import opening_overview, user_games
from app.tools.deviations import analyze_repertoire, store_results
from app.tools.games import store_games
from app.tools.pgn_utils import san_line_to_uci
from app.tools.repertoire import import_pgn, load_tree, save_tree


def _g(moves: str, color: str, gid: str, result: str = "draw") -> NormalizedGame:
    return NormalizedGame(source="lichess", external_id=gid, pgn="", color=color, result=result,
                          opponent="o", moves_uci=san_line_to_uci(moves))


def test_overview_groups_games_and_finds_exits(db) -> None:
    user = User(username="ov_user", lichess_username="x")
    db.add(user)
    db.commit()
    rep = save_tree(db, user.id, import_pgn((FIXTURES_DIR / "repertoire_white.pgn").read_text(), "white", "e4"), "pgn")
    store_games(db, user.id, [
        _g("e4 e5 Nf3 Nc6 Bc4 Bc5", "white", "1", "loss"),   # leaves the repertoire with Bc4
        _g("e4 e5 Nf3 Nc6 Bc4 Nf6", "white", "2", "win"),
        _g("e4 d5 exd5 Qxd5", "white", "3"),                 # opponent plays an uncovered move
        _g("d4 d5 c4 e6", "black", "4"),                     # no black repertoire at all
    ])
    devs, unc = analyze_repertoire(user_games(db, user.id), load_tree(db, rep.id), rep.id, judge=False)
    store_results(db, rep.id, devs, unc)
    ov = opening_overview(db, user.id)
    assert ov["games"] == 4 and ov["repertoires"] == 1
    by_state = {}
    for o in ov["openings"]:
        for state, n in o["states"].items():
            by_state[state] = by_state.get(state, 0) + n
    assert by_state == {"in_book": 0, "you_left": 2, "opponent": 1, "none": 1}
    left = next(o for o in ov["openings"] if o["states"]["you_left"])
    assert left["games"] == 2 and left["results"]["win"] == 1 and left["results"]["loss"] == 1
    top = left["exits"][0]
    assert (top["played_san"], top["repertoire_san"], top["games"]) == ("Bc4", "Bb5", 2)
    assert top["line"] == "1.e4 e5 2.Nf3 Nc6"
    assert top["deviation_id"] is not None  # linked to the stored deviation (full FEN vs key)
    gap = next(o for o in ov["openings"] if o["states"]["opponent"])["exits"][0]
    assert gap["state"] == "opponent" and gap["played_san"] == "d5"
