"""Master move statistics for a position.

Three sources, tried in order:

1. **Lichess masters explorer** (``explorer.lichess.ovh/masters``) when online
   and a ``LICHESS_TOKEN`` is configured (the explorer requires auth).
2. **Local master PGN index** built from any PGN files placed in
   ``backend/data/corpus/masters/`` (for example the CC0 Lichess elite
   database). Real counts and results.
3. **ECO book** fallback derived from the opening tables. Its "game counts"
   are *synthetic*: each (position, move) gets 100 x the number of ECO lines
   that pass through it. They only rank main lines above side lines and are
   labelled ``source="eco-book"`` everywhere they are shown, so they are never
   mistaken for real master statistics (see DECISIONS.md).
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from functools import lru_cache

import chess

from app.config import CORPUS_DIR, DATA_DIR, get_settings
from app.schemas import MasterMove, MasterStats
from app.tools.engine import _Cache
from app.tools.http import get_text
from app.tools.openings import _eco_files
from app.tools.pgn_utils import fen_key, read_pgn_games

MASTERS_DIR = CORPUS_DIR / "masters"
MASTER_INDEX_PLIES = 24


@lru_cache(maxsize=1)
def _eco_book() -> dict[str, dict[str, int]]:
    """fen_key -> {uci: synthetic count} from every ECO line."""
    book: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for path in _eco_files():
        with path.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                board = chess.Board()
                for tok in row["pgn"].split():
                    if tok.endswith("."):
                        continue
                    try:
                        move = board.parse_san(tok)
                    except ValueError:
                        break
                    book[fen_key(board)][move.uci()] += 100
                    board.push(move)
    return {k: dict(v) for k, v in book.items()}


@lru_cache(maxsize=1)
def _pgn_index() -> dict[str, dict[str, list[int]]]:
    """fen_key -> {uci: [games, white_wins, draws, black_wins]} from master PGNs."""
    index: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0, 0, 0]))
    if not MASTERS_DIR.exists():
        return {}
    for path in sorted(MASTERS_DIR.glob("*.pgn")):
        for game in read_pgn_games(path.read_text(encoding="utf-8", errors="ignore")):
            res = game.headers.get("Result", "*")
            slot = {"1-0": 1, "1/2-1/2": 2, "0-1": 3}.get(res)
            board = game.board()
            for ply, move in enumerate(game.mainline_moves()):
                if ply >= MASTER_INDEX_PLIES:
                    break
                entry = index[fen_key(board)][move.uci()]
                entry[0] += 1
                if slot:
                    entry[slot] += 1
                board.push(move)
    return {k: {m: list(v) for m, v in d.items()} for k, d in index.items()}


_remote_cache = _Cache(DATA_DIR / "cache" / "masters_cache.sqlite")  # explorer answers survive restarts


def _explorer(fen: str) -> MasterStats | None:
    s = get_settings()
    if s.offline or not s.lichess_token:
        return None
    hit = _remote_cache.get(fen_key(fen))
    if hit:
        return MasterStats.model_validate({**hit, "fen": fen})
    try:
        body = get_text(
            "https://explorer.lichess.ovh/masters",
            headers={"Authorization": f"Bearer {s.lichess_token}"},
            params={"fen": fen, "moves": 12, "topGames": 0},
            min_interval=0.5,
        )
    except Exception:
        return None
    data = json.loads(body)
    moves = [
        MasterMove(
            uci=m["uci"], san=m["san"], games=m["white"] + m["draws"] + m["black"],
            white=m["white"], draws=m["draws"], black=m["black"],
        )
        for m in data.get("moves", [])
    ]
    stats = MasterStats(fen=fen, total_games=sum(m.games for m in moves), moves=moves, source="lichess-masters")
    _remote_cache.put(fen_key(fen), stats.model_dump())
    return stats


@lru_cache(maxsize=4096)
def master_moves(fen: str) -> MasterStats:
    """Master moves for ``fen``, most popular first."""
    remote = _explorer(fen)
    if remote and remote.total_games:
        return remote
    return _local_stats(fen)


def _local_stats(fen: str) -> MasterStats:
    """Master statistics without the network: local master PGNs, else the ECO book."""
    key = fen_key(fen)
    board = chess.Board(fen) if len(fen.split()) >= 6 else chess.Board(key + " 0 1")

    def san(u: str) -> str:
        return board.san(chess.Move.from_uci(u))

    pgn_hits = _pgn_index().get(key)
    if pgn_hits:
        moves = [MasterMove(uci=u, san=san(u), games=v[0], white=v[1], draws=v[2], black=v[3])
                 for u, v in pgn_hits.items()]
        moves.sort(key=lambda m: m.games, reverse=True)
        return MasterStats(fen=fen, total_games=sum(m.games for m in moves), moves=moves, source="local-pgn")

    book = _eco_book().get(key, {})
    moves = [MasterMove(uci=u, san=san(u), games=c) for u, c in book.items()]
    moves.sort(key=lambda m: m.games, reverse=True)
    return MasterStats(fen=fen, total_games=sum(m.games for m in moves), moves=moves, source="eco-book")


def is_theory(fen: str, move_uci: str, min_share: float = 0.05, local_only: bool = False) -> bool:
    """A move is "theory" if masters play it in >= ``min_share`` of games here.

    ``local_only`` (used when mining a user's games) never waits on the network: it uses an
    already cached explorer answer if there is one, otherwise the local master PGNs and the
    ECO book, where any book move counts as theory. Asking the explorer for every position
    of 200 games used to take minutes at the explorer's rate limit.
    """
    if local_only:
        cached = _remote_cache.get(fen_key(fen))
        stats = MasterStats.model_validate({**cached, "fen": fen}) if cached else _local_stats(fen)
        if stats.source == "eco-book":
            return any(m.uci == move_uci for m in stats.moves)
    else:
        stats = master_moves(fen)
    if not stats.total_games:
        return False
    for m in stats.moves:
        if m.uci == move_uci:
            return m.games / stats.total_games >= min_share
    return False
