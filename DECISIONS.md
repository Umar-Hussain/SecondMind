# Design decisions and assumptions

Rule B0.7 of the specification: when a requirement is unclear, choose the simplest option, write it
down here, and continue.

## Data

1. **Synthetic fixtures.** Offline tests and the demo use synthetic games in the exact Lichess NDJSON
   and Chess.com archive formats (`backend/data/fixtures/make_fixtures.py`). Every planted situation
   (deviations, blunders, gambits, transposition, duplicate) is documented in that file.
2. **Bundled ECO subset.** `backend/data/eco/bundled.tsv` (~110 lines) covers every opening in the
   fixtures. `scripts/download_eco.py` fetches the full CC0 tables; the classifier prefers them.
3. **Master statistics.** Order: Lichess masters explorer (needs `LICHESS_TOKEN`), then a local index of
   any PGNs in `backend/data/corpus/masters/`, then an **ECO book** whose counts are synthetic
   (100 × number of ECO lines through the move). The source is shown in the UI (`eco-book`) so synthetic
   counts are never presented as real master data.
4. **Corpus.** 25 original opening notes (CC BY 4.0) and three public-domain games. No book or course
   text is used.
5. **Gambit baselines** (`objective_eval_cp`) are computed by Stockfish (`scripts/calibrate_gambits.py`),
   never typed by hand.

## Chess rules

6. **Deviation classes.** The spec defines `mistake` (> 80 cp), `harmless` (≤ 30 cp) and `better`
   (> 30 cp better). Losses between 31 and 80 cp were undefined; they are labelled `inaccuracy`.
7. **Theory moves skip the engine in leak mining.** A move played by masters in ≥ 5 % of games is
   trusted as theory and not engine-checked, which saves most Stockfish calls.
8. **Gambit window.** A move is judged by gambit rules inside `theory_end_ply`; main-line gambit moves
   are never flagged even a little past it (the evaluation found three such false positives). After a
   `gambit_deviation` the gambit is considered over and the ordinary rules apply.
9. **A repertoire deviation is a gambit deviation** only when it happens at or after the sacrifice
   (leaving the repertoire on move 3 in a game that later became an Evans Gambit is not one).
10. **Quiz uniqueness.** Requiring "no other move within 30 cp" rejects almost every opening position.
    Instead, all moves within 30 cp of the answer are *accepted* answers, and a quiz with more than
    three acceptable answers is rejected as ambiguous.
11. **Color mismatch on import** is a warning (not an error): every branch on the user's side and none
    on the opponent's side suggests the wrong color, but tiny repertoires can look like that legitimately.

## AI layer

12. **Model.** The project must run at zero cost, so the default provider is **Groq's free tier** with
    `openai/gpt-oss-120b` (open weights), reached through one OpenAI-compatible connector that also
    serves a local Ollama model. Groq's JSON mode guarantees valid JSON; the schema is given in the
    prompt and validated locally, with retries. Quota errors (429) back off, then fall back to
    templates. Claude remains supported (`LLM_PROVIDER=anthropic`, `claude-opus-5-5`, adaptive thinking, effort
    `medium`. Structured output uses `messages.parse(output_format=...)` and is validated again locally.
13. **Guard failure.** The spec says "retry once, then drop the item". For report items we drop the
    *LLM explanation* and show the deterministic template for that item instead, so the leak itself
    (which is engine-verified) is not lost.
14. **Refusals.** A `refusal` stop reason is treated like a guard failure (template fallback).
15. **Agent tool results are compact.** Tools return counts and ids; large objects stay in
    `AgentState`. The model never "reads" long move lists it could misquote.
16. **Embeddings.** sentence-transformers MiniLM when the optional `[rag]` extra is installed; otherwise
    TF-IDF vectors, so the project runs from a clean clone without downloading a model. Vectors are kept
    in memory (the corpus is small) instead of Chroma.
17. **Unguarded modes are never served.** `/report?mode=llm` and `llm_rag` exist only for evaluation;
    the API rejects them.

## Engineering

18. **One batch engine + one engine per live stream.** The batch engine is a locked singleton; each
    WebSocket gets its own process. Shutdown is registered with `threading._register_atexit` because
    python-chess runs the engine on a non-daemon thread (a plain `atexit` hook never ran and the process
    hung on exit).
19. **Engine cache** is a separate SQLite file (`backend/data/cache/engine_cache.sqlite`), keyed by
    FEN, depth, MultiPV and move restriction.
20. **Frontend pins** React 18.3 + react-chessboard 4.7 (the v5 API changed).
21. **Scheduler** is APScheduler in its own process; game-time briefings use `replace_existing` ids.
22. **Live analysis runs in the browser.** Stockfish 19 *lite, single-threaded* WebAssembly (about 1.8 MB)
    runs in a Web Worker, so free hosting only does batch analysis and the guard. The single-threaded
    build needs no COOP/COEP headers. The server WebSocket stays as a fallback. Batch analysis and the
    guard stay on the server because the server cannot trust evaluations sent by a browser.
23. **Telegram removed.** The web app is the only delivery channel; calendar `.ics` reminders remain.
24. **Groq model.** `llama-3.3-70b-versatile` was not available on the account; `openai/gpt-oss-120b`
    was the strongest general model listed by `GET /models`. Override with `LLM_MODEL`.
