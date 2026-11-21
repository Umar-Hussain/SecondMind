"""Theory corpus and hybrid retrieval (spec 9.5, Phase 9).

Corpus

* ``corpus/opening_ideas.json`` — short opening-idea notes (plans, structures,
  typical mistakes), original text by the project authors, CC BY 4.0.
* ``corpus/master_games.pgn`` — public-domain master games, chunked into an
  opening segment (first 12 moves) with players, year and ECO as citation data.

Retrieval = reciprocal rank fusion (RRF) of

* a **dense** ranking: sentence-transformers ``all-MiniLM-L6-v2`` when the
  optional ``[rag]`` extra is installed, otherwise a TF-IDF vector space
  (unigrams + bigrams) so the project still runs offline with no model download;
* a **keyword** ranking: BM25 (``rank_bm25``).

An optional ``eco`` filter boosts chunks of the same ECO code / family, and
every hit carries a ``Citation`` so the verification guard can check that the
LLM only cites documents that were actually retrieved.
"""

from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass
from functools import lru_cache

import chess.pgn
import numpy as np
from rank_bm25 import BM25Okapi

from app.config import CORPUS_DIR
from app.schemas import Citation, RetrievedDoc

RRF_K = 60
_TOKEN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


@dataclass
class Chunk:
    id: str
    text: str
    title: str
    source: str
    eco: str | None
    opening: str
    url: str | None = None
    year: int | None = None
    players: str | None = None
    license: str = ""

    def citation(self) -> Citation:
        return Citation(id=self.id, title=self.title, source=self.source, url=self.url, year=self.year,
                        players=self.players)


def _eco_near(a: str, b: str, span: int = 10) -> bool:
    """Same ECO volume and within ``span`` codes (C60 and C70 are both Ruy Lopez).

    Comparing the first two characters would wrongly split C60-C69 from C70-C79.
    """
    if len(a) != 3 or len(b) != 3 or a[0] != b[0] or not (a[1:].isdigit() and b[1:].isdigit()):
        return False
    return abs(int(a[1:]) - int(b[1:])) <= span


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower().replace("...", " "))


# ---------------------------------------------------------------------------
# Corpus loading and chunking
# ---------------------------------------------------------------------------


def load_corpus() -> list[Chunk]:
    chunks: list[Chunk] = []
    ideas = json.loads((CORPUS_DIR / "opening_ideas.json").read_text(encoding="utf-8"))
    for d in ideas["docs"]:
        chunks.append(Chunk(id=d["id"], text=d["text"], title=d["title"], source="RepertoireAI opening notes",
                            eco=d.get("eco"), opening=d["opening"], year=2026, license=ideas["_license"]))

    pgn_path = CORPUS_DIR / "master_games.pgn"
    if pgn_path.exists():
        stream = io.StringIO(pgn_path.read_text(encoding="utf-8"))
        n = 0
        while (game := chess.pgn.read_game(stream)) is not None:
            n += 1
            h = game.headers
            board = game.board()
            sans = []
            for i, move in enumerate(game.mainline_moves()):
                if i >= 24:  # opening segment only: 12 moves
                    break
                sans.append(board.san(move))
                board.push(move)
            numbered = " ".join(f"{i // 2 + 1}. {s}" if i % 2 == 0 else s for i, s in enumerate(sans))
            year = int(h.get("Date", "0")[:4]) if h.get("Date", "?")[:4].isdigit() else None
            players = f"{h.get('White')} - {h.get('Black')}"
            text = (f"Master game {players}, {h.get('Site', '')} {year}. {h.get('Opening', '')} "
                    f"({h.get('ECO', '')}). Opening moves: {numbered}. Result {h.get('Result')}.")
            chunks.append(Chunk(id=f"game-{n:03d}-{h.get('ECO', 'X')}", text=text,
                                title=f"{players}, {year}", source="Master game (public domain)",
                                eco=h.get("ECO"), opening=h.get("Opening", ""), year=year, players=players,
                                license=h.get("Source", "public domain")))
    return chunks


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------


class _DenseEncoder:
    """sentence-transformers if installed, otherwise TF-IDF vectors."""

    def __init__(self, texts: list[str]) -> None:
        self.kind = "tfidf"
        try:  # pragma: no cover - optional heavy dependency
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer("all-MiniLM-L6-v2")
            self.kind = "minilm"
            self.matrix = self._model.encode(texts, normalize_embeddings=True)
        except Exception:
            from sklearn.feature_extraction.text import TfidfVectorizer

            self._vec = TfidfVectorizer(tokenizer=tokenize, ngram_range=(1, 2), sublinear_tf=True,
                                        token_pattern=None, lowercase=False)
            m = self._vec.fit_transform(texts)
            self.matrix = m

    def scores(self, query: str) -> np.ndarray:
        if self.kind == "minilm":  # pragma: no cover
            q = self._model.encode([query], normalize_embeddings=True)
            return (self.matrix @ q.T).ravel()
        q = self._vec.transform([query])
        return (self.matrix @ q.T).toarray().ravel()


class TheoryIndex:
    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks
        texts = [f"{c.title}. {c.opening}. {c.text}" for c in chunks]
        self.dense = _DenseEncoder(texts)
        self.bm25 = BM25Okapi([tokenize(t) for t in texts])
        self.by_id = {c.id: c for c in chunks}

    def _rank(self, scores: np.ndarray) -> list[int]:
        return [int(i) for i in np.argsort(-scores) if scores[i] > 0]

    def retrieve(self, query: str, eco: str | None = None, k: int = 6, mode: str = "hybrid") -> list[RetrievedDoc]:
        """Top-k chunks. ``mode``: hybrid | dense | bm25 (the alternatives are kept for evaluation)."""
        dense_rank = self._rank(self.dense.scores(query)) if mode in ("hybrid", "dense") else []
        bm25_rank = self._rank(np.asarray(self.bm25.get_scores(tokenize(query)))) if mode in ("hybrid", "bm25") else []
        fused: dict[int, float] = {}
        for ranking in (dense_rank, bm25_rank):
            for r, idx in enumerate(ranking):
                fused[idx] = fused.get(idx, 0.0) + 1.0 / (RRF_K + r + 1)
        if eco:
            for idx in list(fused):
                c_eco = self.chunks[idx].eco or ""
                if c_eco == eco:
                    fused[idx] += 2.0 / RRF_K
                elif _eco_near(c_eco, eco):
                    fused[idx] += 0.5 / RRF_K
        ordered = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:k]
        return [RetrievedDoc(id=self.chunks[i].id, text=self.chunks[i].text, score=round(s, 5),
                             citation=self.chunks[i].citation(), eco=self.chunks[i].eco,
                             opening=self.chunks[i].opening) for i, s in ordered]


@lru_cache(maxsize=1)
def get_index() -> TheoryIndex:
    return TheoryIndex(load_corpus())


def retrieve(query: str, eco: str | None = None, k: int = 6, mode: str = "hybrid") -> list[RetrievedDoc]:
    return get_index().retrieve(query, eco=eco, k=k, mode=mode)


def master_games_for(eco: str | None, opening: str = "", k: int = 2) -> list[Citation]:
    """Cited master games that illustrate an opening (same ECO family first)."""
    games = [c for c in get_index().chunks if c.id.startswith("game-")]
    def score(c: Chunk) -> int:
        s = 0
        if eco and c.eco == eco:
            s += 3
        elif eco and c.eco and c.eco[:2] == eco[:2]:
            s += 1
        if opening and c.opening and opening.split(":")[0].lower() in c.opening.lower():
            s += 2
        return s
    ranked = sorted(games, key=score, reverse=True)
    return [c.citation() for c in ranked[:k] if score(c) > 0]
