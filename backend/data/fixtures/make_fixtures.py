"""Generate the offline fixture dataset (synthetic, deterministic).

Run from the repository root::

    python backend/data/fixtures/make_fixtures.py

The fixtures imitate the exact response formats of the Lichess games export
(NDJSON) and the Chess.com Published-Data API (archives list + monthly
archives), so the real clients are exercised end to end without network.

Every game here is *synthetic* — written for this project to plant known
situations that the tests and the evaluation check for:

* repeated repertoire deviations with different game counts (ranking test),
* a clear repeated blunder (leak mining test),
* harmless deviations,
* opponent moves the repertoire does not cover (uncovered lines),
* a transposition into the repertoire tree,
* correctly played gambits and gambit deviations (gambit false-positive test),
* a duplicate game across platforms (merge test),
* an opponent with repeated openings and a weak spot (scouting test).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import chess
import chess.pgn

HERE = Path(__file__).resolve().parent
PLAYER_LICHESS = "demo_player"
PLAYER_CHESSCOM = "demo_player_cc"
OPPONENT = "rival_player"
BASE_DATE = datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc)


@dataclass
class Spec:
    """A synthetic game: the player's color, SAN moves and result for the player."""

    color: str
    moves: str
    result: str  # win | draw | loss  (player POV)
    opponent: str = "club_opponent"
    platform: str = "lichess"
    note: str = ""


# ---------------------------------------------------------------------------
# The player's games. Repertoire (see repertoire_white.pgn / repertoire_black.pgn):
#   White: 1.e4 e5 2.Nf3 Nc6 3.Bb5 a6 4.Ba4 Nf6 5.O-O
#          1.e4 c5 2.Nf3 d6 3.d4 cxd4 4.Nxd4 Nf6 5.Nc3
#          1.e4 c6 2.d4 d5 3.e5 Bf5 4.Nf3 e6 5.Be2
#          1.e4 e6 2.d4 d5 3.e5 c5 4.c3
#   Black: 1.e4 c6 2.d4 d5 3.e5 Bf5 4.Nf3 e6 5.Be2 c5
#          1.e4 c6 2.d4 d5 3.Nc3 dxe4 4.Nxe4 Bf5
#          1.e4 c6 2.Nc3 d5 (3.d4 transposes)
#          1.d4 d5 2.c4 c6
# ---------------------------------------------------------------------------

PLAYER_GAMES: list[Spec] = [
    # --- In-book games (no deviation expected) ---------------------------
    Spec("white", "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7 Re1 b5 Bb3 d6", "win", note="in book"),
    Spec("white", "e4 c6 d4 d5 e5 Bf5 Nf3 e6 Be2 c5 O-O Nc6", "draw", note="in book"),
    Spec("black", "e4 c6 d4 d5 e5 Bf5 Nf3 e6 Be2 c5 O-O Nc6", "win", note="in book"),
    Spec("black", "d4 d5 c4 c6 Nf3 Nf6 Nc3 dxc4", "draw", note="in book"),
    # --- Transposition: 2.Nc3 d5 3.d4 reaches the 2.d4 d5 3.Nc3 node ------
    Spec("black", "e4 c6 Nc3 d5 d4 dxe4 Nxe4 Bf5 Ng3 Bg6", "draw", note="transposition, in book"),
    # --- Planted deviation A (most frequent, 4 games): 3.Bc4 instead of 3.Bb5
    Spec("white", "e4 e5 Nf3 Nc6 Bc4 Bc5 c3 Nf6 d3 d6", "win", note="dev A"),
    Spec("white", "e4 e5 Nf3 Nc6 Bc4 Nf6 d3 Be7 O-O O-O", "draw", note="dev A"),
    Spec("white", "e4 e5 Nf3 Nc6 Bc4 Bc5 O-O Nf6 d3 d6", "loss", note="dev A"),
    Spec("white", "e4 e5 Nf3 Nc6 Bc4 Nf6 Ng5 d5 exd5 Na5", "win", note="dev A", platform="chesscom"),
    # --- Planted blunder B (3 games): 4.Nxe5?? instead of 4.Ba4 -------------
    Spec("white", "e4 e5 Nf3 Nc6 Bb5 a6 Nxe5 Nxe5 Ba4 b5 Bb3 Bb7", "loss", note="blunder B"),
    Spec("white", "e4 e5 Nf3 Nc6 Bb5 a6 Nxe5 Nxe5 d4 axb5 dxe5 Bb4+", "loss", note="blunder B"),
    Spec("white", "e4 e5 Nf3 Nc6 Bb5 a6 Nxe5 Nxe5 Bxa6 bxa6 d4 Ng6", "loss", note="blunder B",
         platform="chesscom"),
    # --- Planted mistake C (2 games): 5.e5? in the Najdorf structure -------
    Spec("white", "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 e5 dxe5 Nb3 Qxd1+ Kxd1 Nc6", "loss", note="mistake C"),
    Spec("white", "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 e5 dxe5 Nf3 Qxd1+ Kxd1 Nc6", "loss", note="mistake C",
         platform="chesscom"),
    # --- Black deviation D (2 games): 4...Bg4 instead of 4...e6 ------------
    Spec("black", "e4 c6 d4 d5 e5 Bf5 Nf3 Bg4 Be2 e6 O-O Nd7", "draw", note="dev D"),
    Spec("black", "e4 c6 d4 d5 e5 Bf5 Nf3 Bg4 h3 Bxf3 Qxf3 e6", "loss", note="dev D"),
    # --- Uncovered opponent lines -----------------------------------------
    Spec("white", "e4 d5 exd5 Qxd5 Nc3 Qa5 d4 Nf6", "win", note="uncovered 1...d5"),
    Spec("white", "e4 d5 exd5 Nf6 d4 Nxd5 Nf3 g6", "draw", note="uncovered 1...d5"),
    Spec("white", "e4 d5 exd5 Qxd5 Nc3 Qd6 d4 Nf6", "win", note="uncovered 1...d5", platform="chesscom"),
    Spec("white", "e4 Nf6 e5 Nd5 d4 d6 Nf3 Bg4", "draw", note="uncovered 1...Nf6"),
    Spec("black", "e4 c6 d4 d5 exd5 cxd5 c4 Nf6 Nc3 e6", "draw", note="uncovered 3.exd5"),
    # --- Gambits the player plays correctly (must NOT be flagged) ----------
    Spec("white", "e4 e5 f4 exf4 Nf3 g5 h4 g4 Ne5 Nf6 Bc4 d5 exd5 Bd6", "win", note="King's Gambit theory"),
    Spec("white", "e4 e5 Nf3 Nc6 Bc4 Bc5 b4 Bxb4 c3 Ba5 d4 exd4 O-O Nge7", "win", note="Evans theory"),
    Spec("white", "e4 c5 d4 cxd4 c3 dxc3 Nxc3 Nc6 Nf3 d6 Bc4 e6 O-O Nf6", "draw", note="Smith-Morra theory"),
    Spec("white", "e4 e5 d4 exd4 c3 dxc3 Bc4 cxb2 Bxb2 d5 Bxd5 Nf6", "win", note="Danish theory"),
    Spec("black", "d4 e5 dxe5 Nc6 Nf3 Qe7 Bf4 Qb4+ Bd2 Qxb2 Nc3 Bb4", "loss", note="Englund as Black"),
    # --- Gambit deviation: King's Gambit, 4.d4? gives the pawn back badly --
    Spec("white", "e4 e5 f4 exf4 Nf3 g5 Bc4 g4 Qe2 gxf3 Qxf3 Qh4+", "loss", note="KG deviation"),
    # --- Defender trap: player (White) faces the Englund and falls for it --
    Spec("white", "d4 e5 dxe5 Nc6 Nf3 Qe7 Bf4 Qb4+ Bd2 Qxb2 Bc3 Bb4 Qd2 Bxc3", "loss",
         note="Englund trap (defender)"),
    # --- Cross-platform duplicate of the first in-book game ---------------
    Spec("white", "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7 Re1 b5 Bb3 d6", "win", note="dup of game 0",
         platform="chesscom"),
]

# The opponent always answers 1.e4 with the Caro-Kann and leaves theory early
# in the Advance with 4...h5?! ; as White plays 1.d4 and the London.
OPPONENT_GAMES: list[Spec] = (
    [Spec("black", "e4 c6 d4 d5 e5 Bf5 Nf3 e6 Be2 Nd7 O-O h6", r, opponent="x") for r in ("loss", "draw", "loss")]
    + [Spec("black", "e4 c6 d4 d5 e5 Bf5 h4 h5 c4 e6 Nc3 Ne7", r, opponent="x") for r in ("loss", "loss")]
    + [Spec("black", "e4 c6 d4 d5 Nc3 dxe4 Nxe4 Bf5 Ng3 Bg6 h4 h6", r, opponent="x") for r in ("draw", "win")]
    + [Spec("black", "d4 d5 c4 e6 Nc3 Nf6 Bg5 Be7", "draw", opponent="x")]
    + [Spec("white", "d4 d5 Bf4 Nf6 e3 e6 Nf3 c5 c3 Nc6", r, opponent="x") for r in ("win", "win", "draw", "loss")]
    + [Spec("white", "d4 Nf6 Bf4 g6 e3 Bg7 Nf3 O-O Be2 d6", r, opponent="x") for r in ("win", "draw")]
    + [Spec("white", "d4 e5 dxe5 Nc6 Nf3 Qe7 Bf4 Qb4+ Bd2 Qxb2", "loss", opponent="x")]
)


def _play(moves_san: str) -> tuple[chess.pgn.Game, list[str], list[str]]:
    """Replay SAN moves, return a PGN game plus SAN and UCI lists (validates legality)."""
    board = chess.Board()
    game = chess.pgn.Game()
    node: chess.pgn.GameNode = game
    sans, ucis = [], []
    for san in moves_san.split():
        move = board.parse_san(san)  # raises if a fixture move is illegal
        sans.append(board.san(move))
        ucis.append(move.uci())
        node = node.add_variation(move)
        board.push(move)
    return game, sans, ucis


def _clocks(n_plies: int, initial: int, seed: int) -> list[int]:
    """Deterministic fake clock trace in centiseconds (Lichess style)."""
    clocks, w, b = [], initial * 100, initial * 100
    for ply in range(n_plies):
        spend = (300 + ((seed * 37 + ply * 53) % 900)) if ply > 4 else 100
        if ply % 2 == 0:
            w -= spend
            clocks.append(w)
        else:
            b -= spend
            clocks.append(b)
    return clocks


def _result_tag(color: str, result: str) -> tuple[str, str | None]:
    if result == "draw":
        return "1/2-1/2", None
    white_won = (color == "white") == (result == "win")
    return ("1-0", "white") if white_won else ("0-1", "black")


def _lichess_record(i: int, spec: Spec, me: str) -> dict:
    game, sans, ucis = _play(spec.moves)
    played = BASE_DATE + timedelta(days=i, hours=i % 5)
    res, winner = _result_tag(spec.color, spec.result)
    white = me if spec.color == "white" else spec.opponent
    black = spec.opponent if spec.color == "white" else me
    game.headers.update({"Event": "Rated Rapid game", "Site": f"https://lichess.org/fx{i:06d}",
                         "White": white, "Black": black, "Result": res,
                         "UTCDate": played.strftime("%Y.%m.%d"), "UTCTime": played.strftime("%H:%M:%S")})
    rec = {
        "id": f"fx{i:06d}",
        "rated": True,
        "variant": "standard",
        "speed": "rapid",
        "perf": "rapid",
        "createdAt": int(played.timestamp() * 1000),
        "lastMoveAt": int((played + timedelta(minutes=20)).timestamp() * 1000),
        "status": "resign" if winner else "draw",
        "players": {
            "white": {"user": {"name": white, "id": white.lower()}, "rating": 1600 if white == me else 1580 + i},
            "black": {"user": {"name": black, "id": black.lower()}, "rating": 1600 if black == me else 1590 + i},
        },
        "moves": " ".join(sans),
        "clocks": _clocks(len(sans), 600, i),
        "clock": {"initial": 600, "increment": 0, "totalTime": 600},
        "pgn": str(game),
        "_fixture_note": spec.note,
    }
    if winner:
        rec["winner"] = winner
    return rec


def _chesscom_record(i: int, spec: Spec, me: str) -> dict:
    game, sans, _ = _play(spec.moves)
    played = BASE_DATE + timedelta(days=i, hours=i % 5)
    res, winner = _result_tag(spec.color, spec.result)
    white = me if spec.color == "white" else spec.opponent
    black = spec.opponent if spec.color == "white" else me
    # Chess.com PGNs carry [%clk h:mm:ss] comments after every move.
    clocks = _clocks(len(sans), 600, i)
    node = game
    for c in clocks:
        node = node.variations[0]
        secs = c // 100
        node.comment = f"[%clk {secs // 3600}:{(secs % 3600) // 60:02d}:{secs % 60:02d}]"
    game.headers.update({"Event": "Live Chess", "Site": "Chess.com", "White": white, "Black": black,
                         "Result": res, "Date": played.strftime("%Y.%m.%d"),
                         "Link": f"https://www.chess.com/game/live/9{i:08d}"})

    def side(name: str, colr: str) -> dict:
        if winner is None:
            r = "agreed"
        else:
            r = "win" if winner == colr else "resigned"
        return {"username": name, "rating": 1600, "result": r}

    return {
        "url": f"https://www.chess.com/game/live/9{i:08d}",
        "pgn": str(game),
        "time_control": "600",
        "end_time": int((played + timedelta(minutes=20)).timestamp()),
        "rated": True,
        "time_class": "rapid",
        "rules": "chess",
        "white": side(white, "white"),
        "black": side(black, "black"),
        "_fixture_note": spec.note,
    }


def write_player_fixtures() -> None:
    lichess_dir, chesscom_dir = HERE / "lichess", HERE / "chesscom"
    lichess_dir.mkdir(exist_ok=True)
    chesscom_dir.mkdir(exist_ok=True)

    lichess_lines: list[str] = []
    months: dict[str, list[dict]] = {}
    for i, spec in enumerate(PLAYER_GAMES):
        if spec.platform == "lichess":
            lichess_lines.append(json.dumps(_lichess_record(i, spec, PLAYER_LICHESS)))
        else:
            # The cross-platform duplicate reuses the date of game 0 so the merge can detect it.
            idx = 0 if "dup" in spec.note else i
            rec = _chesscom_record(idx, spec, PLAYER_CHESSCOM)
            if "dup" in spec.note:
                rec["url"] = rec["url"].replace("game/live/9", "game/live/8")
            month = datetime.fromtimestamp(rec["end_time"], tz=timezone.utc).strftime("%Y/%m")
            months.setdefault(month, []).append(rec)

    # Lichess returns newest first.
    (lichess_dir / f"games_{PLAYER_LICHESS}.ndjson").write_text("\n".join(reversed(lichess_lines)) + "\n")

    base = f"https://api.chess.com/pub/player/{PLAYER_CHESSCOM}/games"
    archives = {"archives": [f"{base}/{m}" for m in sorted(months)]}
    (chesscom_dir / f"archives_{PLAYER_CHESSCOM}.json").write_text(json.dumps(archives, indent=1))
    for m, games in months.items():
        (chesscom_dir / f"{PLAYER_CHESSCOM}_{m.replace('/', '_')}.json").write_text(
            json.dumps({"games": games}, indent=1))

    # An account with no archives, and a 404 marker for an unknown user.
    (chesscom_dir / "archives_empty_user.json").write_text(json.dumps({"archives": []}))
    (chesscom_dir / "archives_ghost_user.404").write_text("")


def write_opponent_fixtures() -> None:
    lines = [json.dumps(_lichess_record(1000 + i, s, OPPONENT)) for i, s in enumerate(OPPONENT_GAMES)]
    (HERE / "lichess" / f"games_{OPPONENT}.ndjson").write_text("\n".join(reversed(lines)) + "\n")


if __name__ == "__main__":
    write_player_fixtures()
    write_opponent_fixtures()
    print(f"wrote {len(PLAYER_GAMES)} player games and {len(OPPONENT_GAMES)} opponent games")
