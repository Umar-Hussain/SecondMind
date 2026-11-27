"""SecondMind evaluation (retrieval, gambit handling, recommender, guard).

    python eval/run_eval.py               # everything that can run (offline, fixtures)
    python eval/run_eval.py --only retrieval gambit
    python eval/run_eval.py --runs 3      # repeat LLM conditions 3 times (needs LLM_API_KEY)

Components, each with a labelled set of >= 50 examples, metrics, a baseline,
error analysis and latency:

1. retrieval    — hybrid RRF vs dense-only vs BM25-only; Recall@1/3/5, MRR.
2. gambit       — detection accuracy and gambit false-positive rate vs a naive
                  engine-only blunder rule.
3. recommender  — soundness (<= 30 cp from a deeper Stockfish search), share of
                  master moves, vs "always the most popular master move".
4. guard        — detection of hallucinated moves / fake citations in generated
                  explanations vs a legality-only baseline.
5. deviations   — precision / recall of planted repertoire deviations, ranking
                  correctness, no in-book false positives (functional test).
6. llm          — conditions 0 (no LLM), A (LLM only), B (LLM+RAG), C (full,
                  guarded): illegal/unverified-move rate, citation validity,
                  latency, tokens and cost. Runs only with an API key.

Results: eval/results/*.csv and eval/results/summary.md.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("OFFLINE", "1")
sys.path.insert(0, str(ROOT / "backend"))

import chess  # noqa: E402

from app.config import FIXTURES_DIR  # noqa: E402
from app.schemas import Citation, NormalizedGame, RetrievedDoc  # noqa: E402
from app.tools import chesscom, engine, gambits, lichess, masters, rag, verify  # noqa: E402
from app.tools.deviations import analyze_repertoire  # noqa: E402
from app.tools.games import merge_games  # noqa: E402
from app.tools.leaks import analyze_game, mine_leaks  # noqa: E402
from app.tools.pgn_utils import san_line_to_uci  # noqa: E402
from app.tools.recommend import recommend_move  # noqa: E402
from app.tools.repertoire import import_pgn  # noqa: E402

RESULTS = ROOT / "eval" / "results"
DATASETS = ROOT / "eval" / "datasets"
DEPTH = 12          # system depth during evaluation
REF_DEPTH = 16      # deeper reference search for soundness checks
# $/token per provider: Groq and Ollama are free here (free tier / local); Claude Opus 5.5 list price.
PRICES = {"anthropic": (4.0 / 1e6, 20.0 / 1e6), "groq": (0.0, 0.0), "ollama": (0.0, 0.0), "openai_compat": (0.0, 0.0)}


def pct(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))], 1)


def write_csv(name: str, rows: list[dict]) -> None:
    if not rows:
        return
    RESULTS.mkdir(parents=True, exist_ok=True)
    with (RESULTS / f"{name}.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def fixture_games() -> list[NormalizedGame]:
    return merge_games(lichess.fetch_games("demo_player"), chesscom.fetch_games("demo_player_cc"))


# ---------------------------------------------------------------------------
# 1. Retrieval
# ---------------------------------------------------------------------------


def eval_retrieval() -> dict:
    data = json.loads((DATASETS / "retrieval_queries.json").read_text(encoding="utf-8"))["queries"]
    rag.get_index()  # build once, outside the latency measurement
    rows, summary, failures = [], {}, []
    for mode in ("hybrid", "dense", "bm25"):
        for use_eco in (True, False):
            name = f"{mode}{'+eco' if use_eco else ''}"
            r1 = r3 = r5 = 0
            rr, lat = [], []
            for item in data:
                t = time.perf_counter()
                hits = rag.retrieve(item["q"], eco=item["eco"] if use_eco else None, k=5, mode=mode)
                lat.append((time.perf_counter() - t) * 1000)
                ids = [h.id for h in hits]
                gold = set(item["gold"])
                rank = next((i + 1 for i, x in enumerate(ids) if x in gold), None)
                r1 += rank == 1
                r3 += rank is not None and rank <= 3
                r5 += rank is not None
                rr.append(1 / rank if rank else 0.0)
                if rank != 1:  # every miss at rank 1, for error analysis across systems
                    failures.append({"system": name, "query": item["q"], "gold": "|".join(item["gold"]),
                                     "rank": rank, "got": "|".join(ids[:3])})
            n = len(data)
            row = {"system": name, "n": n, "recall@1": round(r1 / n, 3), "recall@3": round(r3 / n, 3),
                   "recall@5": round(r5 / n, 3), "mrr": round(sum(rr) / n, 3),
                   "latency_ms_median": pct(lat, 0.5), "latency_ms_p95": pct(lat, 0.95)}
            rows.append(row)
            summary[name] = row
    write_csv("retrieval", rows)
    write_csv("retrieval_failures", failures)
    return {"rows": rows, "failures": failures}


# ---------------------------------------------------------------------------
# 2. Gambit handling
# ---------------------------------------------------------------------------


def gambit_cases() -> list[dict]:
    """>= 50 labelled games: correct gambit play, gambit deviations, defender traps, non-gambit games."""
    cases: list[dict] = []
    for g in json.loads((ROOT / "backend" / "data" / "gambits.json").read_text())["gambits"]:
        if g["soundness"] == "not_a_real_gambit":
            continue
        for line in g["theory_lines"]:
            ucis = san_line_to_uci(line)
            # The full theory line and a shorter prefix, both played by the gambiteer.
            for cut in sorted({len(ucis), max(len(g["trigger"].split()) + 2, len(ucis) - 4)}):
                cases.append({"id": f"{g['id']}:{cut}", "moves": ucis[:cut], "color": g["side"],
                              "gambit": g["id"], "expect_flags": 0, "kind": "theory"})
    planted = [
        ("kg_dev", "e4 e5 f4 exf4 Nf3 g5 Bc4 g4 Qe2 gxf3 Qxf3 Qh4+", "white", "kings_gambit", "gambit_deviation"),
        ("englund_trap", "d4 e5 dxe5 Nc6 Nf3 Qe7 Bf4 Qb4+ Bd2 Qxb2 Bc3 Bb4", "white", "englund_gambit",
         "defender_trap"),
        ("evans_dev", "e4 e5 Nf3 Nc6 Bc4 Bc5 b4 Bxb4 c3 Ba5 a3 Nf6 d3 O-O", "white", "evans_gambit",
         "gambit_deviation"),
        ("danish_dev", "e4 e5 d4 exd4 c3 dxc3 Bc4 cxb2 Qb3 bxc1=Q+ Ke2", "white", "danish_gambit",
         "gambit_deviation"),
        ("morra_dev", "e4 c5 d4 cxd4 c3 dxc3 Nxc3 Nc6 Nf3 d6 Bc4 e6 Qb3 Nf6 Nb5 a6", "white", "smith_morra",
         "gambit_deviation"),
    ]
    for cid, moves, color, gid, kind in planted:
        cases.append({"id": cid, "moves": san_line_to_uci(moves), "color": color, "gambit": gid,
                      "expect_flags": 1, "kind": kind})
    for g in fixture_games():
        if gambits.detect_gambit(g.moves_uci, g.color) is None:
            cases.append({"id": f"fixture:{g.external_id}", "moves": g.moves_uci, "color": g.color,
                          "gambit": None, "expect_flags": None, "kind": "non_gambit"})
    for g in lichess.fetch_games("rival_player"):
        cases.append({"id": f"rival:{g.external_id}", "moves": g.moves_uci, "color": g.color,
                      "gambit": "detect", "expect_flags": None, "kind": "opponent"})
    return cases


def eval_gambit() -> dict:
    cases = gambit_cases()
    rows, errors = [], []
    det_ok = det_n = 0
    fp_system = fp_naive = theory_moves = 0
    dev_found = dev_n = 0
    lat = []
    for c in cases:
        t = time.perf_counter()
        match = gambits.detect_gambit(c["moves"], c["color"])
        detected = match.gambit.id if match else None
        if c["gambit"] not in ("detect",):
            det_n += 1
            ok = detected == c["gambit"]
            det_ok += ok
            if not ok:
                errors.append({"case": c["id"], "problem": f"detected {detected}, expected {c['gambit']}"})
        game = NormalizedGame(source="lichess", external_id=c["id"], pgn="", color=c["color"], result="draw",
                              opponent="x", moves_uci=c["moves"])
        flags = analyze_game(game, depth=DEPTH) if c["kind"] in ("theory", "gambit_deviation", "defender_trap") \
            else []
        lat.append((time.perf_counter() - t) * 1000)
        if c["kind"] == "theory":
            # Baseline: naive engine rule flags any player move losing > 80 cp.
            board = chess.Board()
            me = chess.WHITE if c["color"] == "white" else chess.BLACK
            naive = 0
            for u in c["moves"]:
                if board.turn == me:
                    theory_moves += 1
                    if engine.eval_loss(board.fen(), u, depth=DEPTH) > 80:
                        naive += 1
                board.push_uci(u)
            fp_system += len(flags)
            fp_naive += naive
            if flags:
                errors.append({"case": c["id"], "problem": f"false positive: {[(f.ply, f.played) for f in flags]}"})
            rows.append({"case": c["id"], "kind": c["kind"], "detected": detected, "system_flags": len(flags),
                         "naive_flags": naive})
        elif c["kind"] in ("gambit_deviation", "defender_trap"):
            dev_n += 1
            hit = any(f.kind == c["kind"] for f in flags)
            dev_found += hit
            if not hit:
                errors.append({"case": c["id"], "problem": f"missed {c['kind']}; got {[f.kind for f in flags]}"})
            rows.append({"case": c["id"], "kind": c["kind"], "detected": detected, "system_flags": len(flags),
                         "naive_flags": ""})
        else:
            rows.append({"case": c["id"], "kind": c["kind"], "detected": detected, "system_flags": "",
                         "naive_flags": ""})
    summary = {
        "cases": len(cases),
        "detection_accuracy": round(det_ok / det_n, 3),
        "player_moves_in_gambit_theory": theory_moves,
        "false_positive_rate_system": round(fp_system / max(theory_moves, 1), 3),
        "false_positive_rate_naive_baseline": round(fp_naive / max(theory_moves, 1), 3),
        "deviation_detection_rate": round(dev_found / max(dev_n, 1), 3),
        "latency_ms_median": pct(lat, 0.5), "latency_ms_p95": pct(lat, 0.95),
    }
    write_csv("gambit_cases", rows)
    write_csv("gambit_errors", errors)
    return {"summary": summary, "errors": errors}


# ---------------------------------------------------------------------------
# 3. Recommender
# ---------------------------------------------------------------------------


def recommender_positions(n: int = 50) -> list[tuple[str, str]]:
    seen, out = set(), []
    for g in fixture_games() + lichess.fetch_games("rival_player"):
        board = chess.Board()
        for ply, u in enumerate(g.moves_uci[:14]):
            if ply >= 2:
                key = " ".join(board.fen().split()[:4])
                if key not in seen:
                    seen.add(key)
                    out.append((board.fen(), "white" if board.turn else "black"))
            board.push_uci(u)
    random.Random(7).shuffle(out)
    return out[:n]


def eval_recommender() -> dict:
    rows, errors, lat = [], [], []
    for fen, side in recommender_positions():
        t = time.perf_counter()
        rec = recommend_move(fen, side, depth=DEPTH)
        lat.append((time.perf_counter() - t) * 1000)
        ref = engine.evaluate(fen, depth=REF_DEPTH)
        chosen_loss = max(0, ref.cp_stm - engine.evaluate_moves(fen, [rec.chosen_uci], depth=REF_DEPTH)[rec.chosen_uci])
        stats = masters.master_moves(fen)
        popular = stats.moves[0].uci if stats.moves else None
        pop_loss = (max(0, ref.cp_stm - engine.evaluate_moves(fen, [popular], depth=REF_DEPTH)[popular])
                    if popular else None)
        rows.append({"fen": fen, "chosen": rec.chosen_san, "source": rec.chosen_source, "chosen_loss": chosen_loss,
                     "popular": popular, "popular_loss": pop_loss, "verified": rec.verified,
                     "latency_ms": round(lat[-1], 1)})
        if chosen_loss > 30:
            errors.append({"fen": fen, "chosen": rec.chosen_san, "source": rec.chosen_source,
                           "loss_at_ref_depth": chosen_loss, "reason": rec.reason[:160]})
    n = len(rows)
    with_pop = [r for r in rows if r["popular_loss"] is not None]
    summary = {
        "positions": n,
        "soundness_within_30cp": round(sum(r["chosen_loss"] <= 30 for r in rows) / n, 3),
        "share_master_choice": round(sum(r["source"] == "master" for r in rows) / n, 3),
        "verified_rate": round(sum(bool(r["verified"]) for r in rows) / n, 3),
        "avg_loss_chosen_cp": round(statistics.mean(r["chosen_loss"] for r in rows), 1),
        "baseline_always_popular_soundness": round(sum(r["popular_loss"] <= 30 for r in with_pop) / max(len(with_pop), 1), 3),
        "baseline_avg_loss_popular_cp": round(statistics.mean(r["popular_loss"] for r in with_pop), 1) if with_pop else None,
        "latency_ms_median": pct(lat, 0.5), "latency_ms_p95": pct(lat, 0.95),
    }
    write_csv("recommender", rows)
    write_csv("recommender_errors", errors)
    return {"summary": summary, "errors": errors}


# ---------------------------------------------------------------------------
# 4. Verification guard
# ---------------------------------------------------------------------------


def guard_cases(n_target: int = 60) -> list[dict]:
    """Synthetic generated explanations with known labels, built from real leak positions."""
    leaks = [lk for lk in mine_leaks(fixture_games(), depth=DEPTH) if lk.kind != "gambit_note"]
    docs = [RetrievedDoc(id=c, text="", score=1, citation=Citation(id=c, title=c, source="s"))
            for c in ("idea-ruy-morphy", "idea-sicilian-open", "idea-caro-advance")]
    cases: list[dict] = []
    rnd = random.Random(11)
    i = 0
    while len(cases) < n_target:
        lk = leaks[i % len(leaks)]
        i += 1
        board = chess.Board(lk.fen)
        played = board.san(chess.Move.from_uci(lk.played))
        best = engine.evaluate(lk.fen, depth=DEPTH).best_move_uci
        rec = board.san(chess.Move.from_uci(lk.theory_move or best))
        allowed = verify.allowed_moves_for(lk.fen, [lk.played, lk.theory_move or best])
        legal_unverified = [board.san(m) for m in board.legal_moves if board.san(m) not in allowed]
        variant = len(cases) % 5
        if variant == 0:
            text, cites, label, why = f"{played} drops material; play {rec} instead [idea-ruy-morphy].", \
                ["idea-ruy-morphy"], False, "clean"
        elif variant == 1:
            bad = rnd.choice(legal_unverified)
            text, cites, label, why = f"Better is {bad}, then {rec} [idea-ruy-morphy].", ["idea-ruy-morphy"], \
                True, "legal but unverified move"
        elif variant == 2:
            text, cites, label, why = f"Play {rec} and later Qh7xg8 or Nb9 [idea-ruy-morphy].", \
                ["idea-ruy-morphy"], True, "illegal move"
        elif variant == 3:
            text, cites, label, why = f"{played} loses; {rec} is the main line [idea-invented-source].", \
                ["idea-invented-source"], True, "fake citation"
        else:
            text, cites, label, why = f"After {played} the plan with {rec} is standard.", [], False, "clean, no cite"
        cases.append({"fen": lk.fen, "text": text, "citations": cites, "allowed": sorted(allowed),
                      "is_bad": label, "type": why, "docs": docs})
    return cases


def eval_guard() -> dict:
    cases = guard_cases()
    rows, errors = [], []
    for c in cases:
        t = time.perf_counter()
        r = verify.verify_text_moves(c["text"], c["allowed"]).reasons + \
            verify.verify_citations(c["citations"], c["docs"]).reasons + \
            verify.verify_citations(c["text"], c["docs"]).reasons
        guard_flag = bool(r)
        lat = (time.perf_counter() - t) * 1000
        # Baseline: legality-only check (every move-like token must be legal here; no citation check).
        board = chess.Board(c["fen"])
        baseline_flag = any(verify.parse_move(board, m) is None for m in verify.extract_moves(c["text"]))
        rows.append({"type": c["type"], "is_bad": c["is_bad"], "guard": guard_flag, "baseline": baseline_flag,
                     "latency_ms": round(lat, 3), "text": c["text"]})
        if guard_flag != c["is_bad"]:
            errors.append({"type": c["type"], "text": c["text"], "guard": guard_flag, "reasons": "; ".join(r)})

    def prf(key: str) -> dict:
        tp = sum(r[key] and r["is_bad"] for r in rows)
        fp = sum(r[key] and not r["is_bad"] for r in rows)
        fn = sum((not r[key]) and r["is_bad"] for r in rows)
        p = tp / (tp + fp) if tp + fp else 0.0
        rc = tp / (tp + fn) if tp + fn else 0.0
        return {"precision": round(p, 3), "recall": round(rc, 3), "f1": round(2 * p * rc / (p + rc), 3) if p + rc else 0}

    by_type = {}
    for t in sorted({r["type"] for r in rows}):
        sub = [r for r in rows if r["type"] == t]
        by_type[t] = {"n": len(sub), "guard_flag_rate": round(sum(r["guard"] for r in sub) / len(sub), 2),
                      "baseline_flag_rate": round(sum(r["baseline"] for r in sub) / len(sub), 2)}
    summary = {"cases": len(rows), "guard": prf("guard"), "baseline_legality_only": prf("baseline"),
               "by_type": by_type, "latency_ms_median": pct([r["latency_ms"] for r in rows], 0.5)}
    write_csv("guard", [{k: v for k, v in r.items()} for r in rows])
    write_csv("guard_errors", errors)
    return {"summary": summary, "errors": errors}


# ---------------------------------------------------------------------------
# 5. Repertoire deviations (functional test)
# ---------------------------------------------------------------------------

GOLD_WHITE = {("Bc4", 5), ("Nxe5", 3), ("e5", 2), ("f4", 2), ("d4", 1)}  # d4 appears 3x as separate positions
GOLD_UNCOVERED_WHITE = {("d5", 3), ("Nf6", 1)}


def eval_deviations() -> dict:
    games = fixture_games()
    tree_w = import_pgn((FIXTURES_DIR / "repertoire_white.pgn").read_text(), "white", "e4")
    tree_b = import_pgn((FIXTURES_DIR / "repertoire_black.pgn").read_text(), "black", "Caro")
    t = time.perf_counter()
    dw, uw = analyze_repertoire(games, tree_w, depth=DEPTH)
    db, ub = analyze_repertoire(games, tree_b, depth=DEPTH)
    ms = (time.perf_counter() - t) * 1000
    found = {(d.played_san, d.games_count) for d in dw}
    tp = len(found & GOLD_WHITE)
    counts = [d.games_count for d in dw]
    in_book_reported = [d.played_san for d in dw if d.played_move == d.repertoire_move]
    summary = {
        "white_deviation_groups": len(dw), "gold_groups": len(GOLD_WHITE),
        "recall": round(tp / len(GOLD_WHITE), 3),
        "precision": round(sum(1 for f in found if f[0] in {g[0] for g in GOLD_WHITE}) / max(len(found), 1), 3),
        "ranking_by_game_count_correct": counts == sorted(counts, reverse=True),
        "in_book_false_positives": len(in_book_reported),
        "uncovered_white": sorted({(u.opponent_san, u.games_count) for u in uw}),
        "uncovered_recall": round(len({(u.opponent_san, u.games_count) for u in uw} & GOLD_UNCOVERED_WHITE)
                                  / len(GOLD_UNCOVERED_WHITE), 3),
        "black_deviations": [(d.played_san, d.games_count, d.classification) for d in db],
        "black_uncovered": [(u.opponent_san, u.games_count) for u in ub],
        "classifications_white": {d.played_san + str(i): d.classification for i, d in enumerate(dw)},
        "latency_ms_total": round(ms, 1),
    }
    write_csv("deviations", [d.model_dump(include={"played_san", "repertoire_san", "games_count",
                                                    "classification", "avg_eval_loss", "recommended_san",
                                                    "recommended_source"}) for d in dw + db])
    return {"summary": summary}


# ---------------------------------------------------------------------------
# 6. LLM conditions 0 / A / B / C
# ---------------------------------------------------------------------------


def eval_llm(runs: int) -> dict:
    from app.llm import client
    from app.models import Run
    from app.db import SessionLocal, init_db
    from app.services import report

    init_db()
    from app.config import get_settings

    settings = get_settings()
    model = settings.anthropic_model if settings.llm_provider == "anthropic" else settings.llm_settings[1]
    price_in, price_out = PRICES.get(settings.llm_provider.lower(), (0.0, 0.0))
    leaks = mine_leaks(fixture_games(), depth=DEPTH)
    items = [lk for lk in leaks if lk.kind != "gambit_note"][:8] + [lk for lk in leaks if lk.kind == "gambit_note"]
    conditions = [("0_template", "template")]
    if client.is_available():
        conditions += [("A_llm_only", "llm"), ("B_llm_rag", "llm_rag"), ("C_full_guard", "full")]
    rows = []
    for cname, mode in conditions:
        for run in range(runs if mode != "template" else 1):
            with SessionLocal() as s:
                start_id = s.query(Run).count()
            lat, illegal, unverified, moves_total, cites_total, cites_bad = [], 0, 0, 0, 0, 0
            for lk in items:
                facts = report.gather_facts(lk, depth=DEPTH, use_rag=mode != "llm")
                t = time.perf_counter()
                try:
                    out, _ = report.explain(facts, mode=mode)
                except Exception as exc:  # unguarded conditions may fail validation entirely
                    out = None
                    print(f"[{cname}] item failed: {exc}")
                lat.append((time.perf_counter() - t) * 1000)
                if out is None:
                    continue
                text = " ".join([out.explanation, out.plan, out.memory_aid])
                board = chess.Board(lk.fen)
                # Same rule as the guard (shared helper), so the metric and the guard agree.
                moves_total += len(verify.extract_moves(text))
                bad = verify.unverified_moves(text, facts.allowed_moves)
                unverified += len(bad)
                illegal += sum(1 for m in bad if verify.parse_move(board, m) is None)
                ids = set(out.citations) | set(verify.cited_ids(text))
                cites_total += len(ids)
                cites_bad += sum(1 for c in ids if c not in {d.id for d in facts.docs})
            with SessionLocal() as s:
                new = s.query(Run).filter(Run.kind == "llm").offset(0).all()[start_id:]
                tin = sum(r.input_tokens for r in new)
                tout = sum(r.output_tokens for r in new)
            rows.append({"condition": cname, "run": run + 1, "items": len(items), "moves_mentioned": moves_total,
                         "illegal_move_rate": round(illegal / moves_total, 3) if moves_total else 0.0,
                         "unverified_move_rate": round(unverified / moves_total, 3) if moves_total else 0.0,
                         "citation_validity": round(1 - cites_bad / cites_total, 3) if cites_total else 1.0,
                         "latency_ms_median": pct(lat, 0.5), "latency_ms_p95": pct(lat, 0.95),
                         "input_tokens": tin, "output_tokens": tout,
                         "provider": f"{settings.llm_provider}:{model}" if mode != "template" else "none",
                         "cost_usd_per_report": round(tin * price_in + tout * price_out, 4)})
    write_csv("llm_conditions", rows)
    return {"rows": rows, "skipped": [] if client.is_available() else ["A", "B", "C (no LLM provider configured)"]}


# ---------------------------------------------------------------------------


def md_table(rows: list[dict]) -> str:
    if not rows:
        return "_no rows_\n"
    keys = list(rows[0].keys())
    out = "| " + " | ".join(keys) + " |\n|" + "---|" * len(keys) + "\n"
    for r in rows:
        out += "| " + " | ".join(str(r[k]) for k in keys) + " |\n"
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=["retrieval", "gambit", "recommender", "guard", "deviations", "llm"])
    ap.add_argument("--runs", type=int, default=3)
    args = ap.parse_args()
    # Partial runs (--only ...) update the previous results instead of replacing them.
    prev = RESULTS / "summary.json"
    out: dict = json.loads(prev.read_text(encoding="utf-8")) if prev.exists() else {}
    for comp in args.only:
        t = time.perf_counter()
        print(f"== {comp} ...", flush=True)
        out[comp] = {"retrieval": eval_retrieval, "gambit": eval_gambit, "recommender": eval_recommender,
                     "guard": eval_guard, "deviations": eval_deviations,
                     "llm": lambda: eval_llm(args.runs)}[comp]()
        print(f"   done in {time.perf_counter() - t:.1f}s", flush=True)

    md = ["# SecondMind evaluation results", "",
          f"Engine depth {DEPTH} (reference {REF_DEPTH}); fixtures; generated by `eval/run_eval.py`.", ""]
    if "retrieval" in out:
        md += ["## 1. Retrieval (50 labelled queries)", "", md_table(out["retrieval"]["rows"]),
               f"Failures (gold not in top 3, hybrid+eco): {len(out['retrieval']['failures'])} — "
               "see `retrieval_failures.csv`.", ""]
    for comp, title in (("gambit", "2. Gambit handling"), ("recommender", "3. Move recommender (50 positions)"),
                        ("guard", "4. Verification guard (60 generated explanations)"),
                        ("deviations", "5. Repertoire deviations (functional test)")):
        if comp in out:
            md += [f"## {title}", "", "```json", json.dumps(out[comp]["summary"], indent=1, default=str), "```", ""]
    if "llm" in out:
        md += ["## 6. LLM conditions (0 = no LLM, A = LLM only, B = LLM+RAG, C = full with guard)", "",
               md_table(out["llm"]["rows"])]
        if out["llm"]["skipped"]:
            md += [f"Skipped: {', '.join(out['llm']['skipped'])}. Set LLM_API_KEY (free Groq key) and rerun "
                   "`python eval/run_eval.py --only llm --runs 3`.", ""]
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "summary.md").write_text("\n".join(md), encoding="utf-8")
    (RESULTS / "summary.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print("\n".join(md))
    engine.shutdown()


if __name__ == "__main__":
    main()
