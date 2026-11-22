"""Old databases had UNIQUE(source, external_id) on games; init_db must switch it to per-user."""

from sqlalchemy import create_engine, inspect, text

from app.db import init_db


def test_old_game_uniqueness_is_replaced(tmp_path) -> None:
    eng = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        c.execute(text(
            "CREATE TABLE games (id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), source VARCHAR(16) NOT NULL, "
            "external_id VARCHAR(128) NOT NULL, pgn TEXT NOT NULL, color VARCHAR(5) NOT NULL, result VARCHAR(5) NOT NULL, "
            "opponent VARCHAR(64) NOT NULL, opponent_rating INTEGER, time_control VARCHAR(32), played_at DATETIME, "
            "moves_uci JSON NOT NULL, clocks JSON, url VARCHAR(256), "
            "CONSTRAINT uq_game_source_ext UNIQUE (source, external_id))"))
        c.execute(text("INSERT INTO users (id) VALUES (1), (2)"))
        c.execute(text("INSERT INTO games (user_id, source, external_id, pgn, color, result, opponent, moves_uci) "
                       "VALUES (1, 'lichess', 'g1', '', 'white', 'win', 'o', '[]')"))
    init_db(eng)
    uniques = [sorted(u["column_names"]) for u in inspect(eng).get_unique_constraints("games")]
    assert uniques == [["external_id", "source", "user_id"]]
    with eng.begin() as c:
        assert c.execute(text("SELECT count(*) FROM games")).scalar() == 1  # data kept
        # The second user can now store the same public game.
        c.execute(text("INSERT INTO games (user_id, source, external_id, pgn, color, result, opponent, moves_uci) "
                       "VALUES (2, 'lichess', 'g1', '', 'black', 'loss', 'o', '[]')"))
    init_db(eng)  # running again is a no-op
