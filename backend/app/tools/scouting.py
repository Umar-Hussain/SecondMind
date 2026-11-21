"""Opponent scouting (spec 5.6, 8.4, Phase 15).

Profile built from the opponent's own games (Lichess or Chess.com):

* openings as White and as Black with frequency and the opponent's score,
* most repeated move sequences (first 10 plies) and how long they stay identical,
* time-trouble tendency from clock data,
* positions where the opponent's own moves lose the most (engine-checked,
  only for positions that recur, so the weakness is a habit, not a one-off),
* gambit usage.

Profiles are cached in ``OpponentProfile`` for 24 hours.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import chess
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import OpponentProfile
from app.schemas import NormalizedGame
from app.tools import chesscom, engine, gambits, lichess
from app.tools.openings import classify, family
from app.tools.pgn_utils import fen_key, line_to_san

CACHE_HOURS = 24
LINE_PLIES = 10


def _score(results: list[str]) -> float:
    return round(sum(1 if r == "win" else 0.5 if r == "draw" else 0 for r in results) / max(len(results), 1), 2)


def fetch_opponent_games(opponent: str, platform: str = "lichess", max_games: int = 300) -> list[NormalizedGame]:
    client = lichess if platform == "lichess" else chesscom
    return client.fetch_games(opponent, max_games=max_games)


def build_profile(opponent: str, games: list[NormalizedGame], depth: int | None = None,
                  weakness_positions: int = 6) -> dict:
    by_color: dict[str, dict[str, list[str]]] = {"white": defaultdict(list), "black": defaultdict(list)}
    eco_of: dict[str, str] = {}
    lines: Counter[tuple[str, ...]] = Counter()
    line_results: dict[tuple[str, ...], list[str]] = defaultdict(list)
    time_trouble = 0
    with_clocks = 0
    gambit_use: Counter[str] = Counter()
    positions: dict[tuple[str, str], list[str]] = defaultdict(list)  # (fen, move) -> results

    for g in games:
        op = classify(g.moves_uci)
        fam = family(op.name)
        by_color[g.color][fam].append(g.result)
        eco_of[fam] = op.eco
        seq = tuple(g.moves_uci[:LINE_PLIES])
        lines[(g.color, *seq)] += 1
        line_results[(g.color, *seq)].append(g.result)
        gm = gambits.detect_gambit(g.moves_uci, g.color)
        if gm and gm.played_by_user:
            gambit_use[gm.gambit.name] += 1
        if g.clocks:
            with_clocks += 1
            mine = g.clocks[0 if g.color == "white" else 1::2]
            start = mine[0] if mine else 0
            if start and any(c < 0.1 * start for c in mine[:30]):
                time_trouble += 1
        board = chess.Board()
        me = chess.WHITE if g.color == "white" else chess.BLACK
        for ply, u in enumerate(g.moves_uci[:16]):
            if board.turn == me:
                positions[(board.fen(), u)].append(g.result)
            board.push_uci(u)

    def openings(color: str) -> list[dict]:
        rows = [{"opening": fam, "eco": eco_of.get(fam, ""), "games": len(r), "score": _score(r)}
                for fam, r in by_color[color].items()]
        return sorted(rows, key=lambda x: -x["games"])

    repeated = []
    for (color, *seq), n in lines.most_common(5):
        if n < 2:
            break
        repeated.append({"color": color, "moves": list(seq), "moves_san": line_to_san(chess.STARTING_FEN, list(seq)),
                         "games": n, "score": _score(line_results[(color, *seq)])})

    # Engine check of recurring positions where the opponent might be going wrong.
    recurring = sorted(((k, v) for k, v in positions.items() if len(v) >= 2), key=lambda kv: -len(kv[1]))
    weaknesses = []
    if engine.is_available():
        for (fen, move), results in recurring[: weakness_positions * 3]:
            loss = engine.eval_loss(fen, move, depth=depth)
            if loss >= 40:
                board = chess.Board(fen)
                weaknesses.append({"fen": fen, "fen_key": fen_key(fen), "move": move, "san": board.san(
                    chess.Move.from_uci(move)), "loss_cp": loss, "games": len(results), "score": _score(results)})
            if len(weaknesses) >= weakness_positions:
                break
    weaknesses.sort(key=lambda w: -(w["loss_cp"] * w["games"]))

    return {
        "opponent": opponent,
        "games_analyzed": len(games),
        "as_white": openings("white"),
        "as_black": openings("black"),
        "repeated_lines": repeated,
        "time_trouble_rate": round(time_trouble / with_clocks, 2) if with_clocks else None,
        "weaknesses": weaknesses,
        "gambits": dict(gambit_use),
    }


def scout(session: Session, opponent: str, platform: str = "lichess", max_games: int = 300,
          depth: int | None = None, refresh: bool = False) -> dict:
    """Return a cached profile (< 24 h) or build a fresh one."""
    row = session.scalars(select(OpponentProfile).where(OpponentProfile.lichess_username == opponent,
                                                        OpponentProfile.platform == platform)).first()
    now = datetime.now(timezone.utc)
    if row and not refresh:
        updated = row.updated_at if row.updated_at.tzinfo else row.updated_at.replace(tzinfo=timezone.utc)
        if now - updated < timedelta(hours=CACHE_HOURS) and not get_settings().offline:
            return {**row.weaknesses_json.get("_profile", {}), "cached": True}
    games = fetch_opponent_games(opponent, platform, max_games)
    profile = build_profile(opponent, games, depth=depth)
    if row is None:
        row = OpponentProfile(lichess_username=opponent, platform=platform)
        session.add(row)
    row.white_repertoire_json = profile["as_white"]
    row.black_repertoire_json = profile["as_black"]
    row.weaknesses_json = {"items": profile["weaknesses"], "_profile": profile}
    row.games_analyzed = profile["games_analyzed"]
    row.updated_at = now
    session.commit()
    return profile
