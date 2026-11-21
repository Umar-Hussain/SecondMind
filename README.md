# SecondMind

**A personalized opening-repertoire and preparation agent for club chess players (1000–2000 Elo).**

SecondMind does the work of a human chess *second*. It reads your Lichess and Chess.com games,
compares them with your own repertoire, ranks where you keep leaving it, finds recurring opening
mistakes, retrieves master theory with citations, recommends practical moves (masters vs. Stockfish),
scouts your next opponent, prepares a briefing with extra lines, and trains you with engine-verified
quizzes and spaced repetition.

> **Central design rule.** Deterministic tools (python-chess, Stockfish, master statistics, the SM-2
> scheduler) produce every chess fact. The LLM diagnoses, explains and orchestrates. Nothing the model
> says about a move, evaluation or source reaches the user unless the **verification guard** has checked it.

Course project — AI-4009 Generative AI, Assignment 3 (Pure Product track).

---

## What works today

| Area | Status |
|---|---|
| Lichess + Chess.com ingestion, cross-platform de-duplication | ✅ |
| Repertoire import (PGN with variations, move list, Lichess study), position-keyed tree, transpositions | ✅ |
| Ranked repertoire deviations (most games first), judged by Stockfish, uncovered opponent lines | ✅ |
| Live Stockfish analysis in the browser (WebAssembly; eval bar, top 3 lines, master stats) | ✅ |
| Leak mining with gambit-aware rules (zero false positives on gambit theory) | ✅ |
| Masters-vs-Stockfish move recommender with stored reasons | ✅ |
| Hybrid RAG (dense + BM25, RRF) with citations | ✅ |
| Verification guard (legality, engine soundness, citations, unverified moves in text) | ✅ |
| LLM client (free Groq by default; Ollama, Claude optional): structured output, retries, run log; agent with 13 tools | ✅ |
| Gap report in 4 conditions (template / LLM / LLM+RAG / guarded) | ✅ |
| Opponent scouting, briefing, extra lines, novelty | ✅ |
| Quizzes + SM-2, `.ics` calendar reminders, scheduled jobs | ✅ |
| React web app (Connect, Repertoire, Deviations, Gap report, Scout, Train, Progress) | ✅ |
| Evaluation harness with labelled sets and baselines | ✅ |
| Accounts (sign up / log in, hashed passwords, user and admin roles) | ✅ |
| Repertoire library: admins publish, users view, copy and edit their own copy | ✅ |
| Repertoire workspace: three-column builder, save / prune moves, notes, live engine | ✅ |
| Concept clustering, chat, tutor hints, repertoire builder, image import | Planned (Assignment 4) |

---

## Quick start

Requirements: Python 3.11+, Node 18+, a Stockfish binary.

```bash
# 1. Backend dependencies
pip install -r requirements.txt   # optional: pip install sentence-transformers (better embeddings)

# 2. Stockfish: download from https://github.com/official-stockfish/Stockfish/releases
#    and point STOCKFISH_PATH at the binary (default: engine/stockfish/...exe)
cp .env.example .env               # then edit .env

# 3. Run the tests (offline, fixtures)
pytest

# 4. Start the backend in demo mode (fixture accounts, no network)
python scripts/dev_backend.py      # http://localhost:8000/docs
#    or with real Lichess / Chess.com calls:
python scripts/dev_backend.py --live

# 5. Start the web app
cd frontend && npm install && npm run dev   # http://localhost:5173
```

Optional:

```bash
python scripts/download_eco.py          # full Lichess ECO tables (CC0) instead of the bundled subset
python scripts/calibrate_gambits.py 18  # recompute gambit baselines with Stockfish
python -m app.services.jobs             # scheduler (daily re-mining and quizzes), run from backend/
python eval/run_eval.py                 # evaluation; LLM conditions A/B/C need LLM_API_KEY
```

**Free LLM.** Set `LLM_API_KEY` to a free Groq key (console.groq.com); the default model is
`openai/gpt-oss-120b`. For a fully local setup use `LLM_PROVIDER=ollama` (no key). Claude is optional
(`LLM_PROVIDER=anthropic`). If the free quota runs out, the app keeps working on templates.

Without any LLM configured everything still runs: explanations fall back to deterministic templates
(evaluation condition 0) and the agent runs a fixed tool plan.

### Accounts and the library

* Anyone can **sign up** with a username and password (passwords are stored as salted PBKDF2 hashes).
* The **admin** account is created at startup from `ADMIN_USERNAME` and `ADMIN_PASSWORD` in `.env`.
  Choose the password yourself; it is never committed.
* Admins **publish** repertoires to the **Library**. Every user can open them read-only and press
  **Add to mine** to get an editable copy; changes to the copy never touch the library original.
* In the workspace, play a move on the board and press **Save move**; **Prune** removes a move and
  everything after it.

### Demo script (about 5 minutes)

1. **Connect**: `demo_player` (Lichess) + `demo_player_cc` (Chess.com) → *Fetch & analyse games*
   (29 games → 28 after removing the cross-platform duplicate).
2. **Repertoire**: paste `backend/data/fixtures/repertoire_white.pgn` → browse the tree.
3. Run the analysis again → **Deviations**: `Bc4` (5 games) tops the list; click `Nxe5` (3 games, mistake)
   to see the board, the recommendation badge, the cited explanation and live Stockfish.
4. **Gap report**: gambit games appear as neutral *gambit notes*, never as blunders.
5. **Scout & prepare**: `rival_player` → likely Caro-Kann / London, repertoire replies, an extra line.
6. **Train**: create quizzes and answer one by moving a piece.

---

## Architecture

```
React web app (board, chess.js) ── .ics calendar reminders
            │  REST + WebSocket
FastAPI  (api/routes.py, api/ws.py)
            │
Agent orchestrator (llm/agent.py) ── LLM (Groq / Ollama / Claude): structured output, tool use
            │                                  ▲ every output passes the verification guard
Deterministic tools (tools/*.py)               │
  lichess · chesscom · games · repertoire · deviations · openings · engine (Stockfish)
  leaks · gambits · masters · recommend · rag · verify · scouting · prep_lines · quiz · srs
            │
SQLite (SQLAlchemy) · engine cache · TF-IDF/MiniLM vectors + BM25 index
```

### Generative-AI techniques → code

| Technique | Where |
|---|---|
| Agentic tool calling (13 tools, step limit, error feedback, audit trail) | `backend/app/llm/agent.py` |
| Retrieval-augmented generation (dense + BM25 + RRF, citations) | `backend/app/tools/rag.py`, `backend/data/corpus/` |
| Prompt engineering (role, verified facts, few-shot, versioned prompts) | `backend/app/llm/prompts.py` |
| Structured output with Pydantic validation and retries | `backend/app/llm/client.py`, `backend/app/schemas.py` |
| Guardrails / verification of LLM output | `backend/app/tools/verify.py`, `backend/app/services/report.py` |
| Workflow automation (scheduled jobs) | `backend/app/services/jobs.py` |
| Integrations (Lichess API, Chess.com API, calendar) | `tools/lichess.py`, `tools/chesscom.py`, `services/delivery.py` |
| Evaluation with baselines (conditions 0/A/B/C) | `eval/run_eval.py`, `eval/results/` |

**Deterministic (not generative) by design:** opening classification, Stockfish evaluation, legality,
master statistics, gambit detection, the move-selection rule and SM-2 scheduling.

---

## Evaluation

`python eval/run_eval.py` writes CSVs and `eval/results/summary.md`. Highlights from the offline run:

| Component | Test set | Result | Baseline |
|---|---|---|---|
| Retrieval | 50 labelled queries | Recall@3 = 1.00, MRR = 0.98 (hybrid + ECO) | BM25 only: MRR 0.93 |
| Gambit handling | 89 games, 256 player moves in gambit theory | 0.0 % false positives, 100 % deviation/trap detection | naive engine rule: 8.6 % false positives |
| Verification guard | 60 generated explanations | F1 = 1.00 | legality-only check: recall 0.33 |
| Repertoire deviations | planted fixture set | precision 1.0, recall 1.0, 0 in-book false positives | — |
| Recommender | 50 positions | see `summary.md` | always the most popular move |

LLM conditions A/B/C (hallucination rate, citation validity, latency, cost) run on the configured
provider; see `eval/results/summary.md` section 6.

---

## Data and licences

* Fixture games are **synthetic**, written for this project (`backend/data/fixtures/make_fixtures.py`).
* Opening notes in `backend/data/corpus/opening_ideas.json` are original text, CC BY 4.0.
* Master games are 19th-century games in the public domain.
* ECO tables: Lichess `chess-openings` (CC0). Offline master statistics without a Lichess token are
  *synthetic counts derived from ECO lines* and are labelled `eco-book` wherever they appear.

See [DECISIONS.md](DECISIONS.md) for every assumption.
