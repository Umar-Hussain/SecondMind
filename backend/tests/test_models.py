"""tables are created and a round-trip insert/read works."""

from sqlalchemy import select

from app.models import Game, Leak, Quiz, Review, User
from app.schemas import GapReport, GapReportItem


def test_user_game_roundtrip(db) -> None:
    user = User(lichess_username="alice", chesscom_username="alice_cc")
    db.add(user)
    db.flush()
    db.add(
        Game(
            user_id=user.id,
            source="lichess",
            external_id="abcd1234",
            pgn="1. e4 e5 *",
            color="white",
            result="win",
            opponent="bob",
            moves_uci=["e2e4", "e7e5"],
        )
    )
    db.commit()

    game = db.scalars(select(Game)).one()
    assert game.moves_uci == ["e2e4", "e7e5"]
    assert game.user_id == user.id


def test_leak_quiz_review_roundtrip(db) -> None:
    user = User(lichess_username="carol")
    db.add(user)
    db.flush()
    leak = Leak(
        user_id=user.id,
        color="white",
        ply=5,
        fen_before="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -",
        played_move="d1h5",
        eval_loss_cp=120.0,
        kind="mistake",
    )
    db.add(leak)
    db.flush()
    quiz = Quiz(leak_id=leak.id, fen=leak.fen_before, question="Best move?", correct_move_uci="e2e4")
    db.add(quiz)
    db.flush()
    db.add(Review(quiz_id=quiz.id, user_id=user.id))
    db.commit()

    review = db.scalars(select(Review)).one()
    assert review.ease == 2.5 and review.repetitions == 0


def test_gap_report_schema_validates() -> None:
    report = GapReport(
        leaks=[
            GapReportItem(
                opening="Sicilian",
                color="black",
                kind="mistake",
                position_fen="x",
                played="e7e5",
                recommended="d7d6",
                eval_loss=90,
            )
        ]
    )
    assert report.leaks[0].recommended == "d7d6"
