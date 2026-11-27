"""opponent profile, extra lines and briefing on fixture data."""

import chess
import pytest

from app.config import FIXTURES_DIR
from app.models import User
from app.services.briefing import prepare
from app.tools import verify
from app.tools.repertoire import import_pgn, save_tree
from app.tools.scouting import build_profile, fetch_opponent_games

pytestmark = pytest.mark.usefixtures("require_engine")
DEPTH = 10


def test_profile_finds_repeated_caro_kann() -> None:
    games = fetch_opponent_games("rival_player")
    p = build_profile("rival_player", games, depth=DEPTH)
    assert p["games_analyzed"] == 15
    assert p["as_black"][0]["opening"].startswith("Caro-Kann")
    assert p["repeated_lines"][0]["games"] >= 3
    assert p["time_trouble_rate"] is not None


def test_briefing_end_to_end(db) -> None:
    user = User(lichess_username="demo_player")
    db.add(user)
    db.commit()
    tree = import_pgn((FIXTURES_DIR / "repertoire_white.pgn").read_text(), "white", "e4 as White")
    save_tree(db, user.id, tree, "pgn")

    briefing, briefing_id = prepare(db, user.id, "rival_player", depth=DEPTH)
    assert briefing_id
    assert briefing.likely_openings
    # Every recommended reply comes from the player's repertoire and is legal.
    assert briefing.recommended_replies
    for r in briefing.recommended_replies:
        assert r["source"] == "repertoire" and verify.is_legal(r["fen"], r["move"])
    # At least one extra line outside the repertoire: short, sound, legal, labelled.
    assert briefing.extra_lines
    for x in briefing.extra_lines:
        assert not x.in_repertoire and x.final_eval_cp >= 0 and len(x.moves) <= 16
        assert x.opponent_color in ("white", "black")  # the board knows which side to prepare
        assert verify.verify_line(x.start_fen or chess.STARTING_FEN, x.moves).ok
    # The novelty is a move for the player, i.e. the side opposite the opponent in their top line.
    if briefing.novelty:
        player = chess.BLACK if briefing.likely_openings[0]["color"] == "white" else chess.WHITE
        assert chess.Board(briefing.novelty["fen"]).turn == player
        assert verify.is_legal(briefing.novelty["fen"], briefing.novelty["move"])
    assert len(briefing.key_ideas) == len(set(briefing.key_ideas))
