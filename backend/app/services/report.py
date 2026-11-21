"""Personalized gap report (spec 5.5, Phase 14).

For each top leak: the player's move, the recommended move (from the
recommender, with its master/engine source and reason), the engine loss, the
retrieved theory, illustrating master games, and an explanation.

Explanations are produced in one of four *conditions* (spec 13), so the
evaluation can measure what each layer adds:

* ``template`` (condition 0) — no LLM: engine facts + fixed templates;
* ``llm`` (A) — LLM only, no retrieval, no guard;
* ``llm_rag`` (B) — LLM with retrieved theory, no guard;
* ``full`` (C) — LLM + RAG + verification guard (retry once, then fall back).

Only ``full`` (or ``template``) output is ever shown to users.
"""

from __future__ import annotations

from dataclasses import dataclass

import chess

from app.llm import client, prompts
from app.schemas import Citation, GapReport, GapReportItem, LeakExplanation, RetrievedDoc
from app.tools import engine, rag, verify
from app.tools.leaks import LeakOut
from app.tools.pgn_utils import uci_to_san
from app.tools.recommend import recommend_move

MODES = ("template", "llm", "llm_rag", "full")


@dataclass
class LeakFacts:
    """Everything verified about one leak, handed to the LLM as FACTS."""

    leak: LeakOut
    played_san: str
    rec_uci: str | None
    rec_san: str
    rec_source: str | None
    rec_reason: str
    rec_verified: bool
    refutation_san: list[str]
    allowed_moves: set[str]
    docs: list[RetrievedDoc]
    master_games: list[Citation]

    def as_dict(self) -> dict:
        lk = self.leak
        return {
            "opening": lk.opening_name, "eco": lk.opening_eco, "color": lk.color, "kind": lk.kind,
            "fen": lk.fen, "played_san": self.played_san, "recommended_san": self.rec_san,
            "recommended_source": self.rec_source, "reason": self.rec_reason,
            "eval_loss_pawns": round(lk.avg_loss / 100, 2), "frequency": lk.frequency, "results": lk.results,
            "engine_line_after_played": self.refutation_san, "gambit": lk.gambit_id,
        }


def gather_facts(lk: LeakOut, depth: int | None = None, use_rag: bool = True) -> LeakFacts:
    played_san = uci_to_san(lk.fen, lk.played)
    if lk.kind == "gambit_note":
        rec_uci, rec_san, source, reason, verified = None, "", None, lk.note, True
    else:
        rec = recommend_move(lk.fen, lk.color, gambit_id=lk.gambit_id, depth=depth)
        rec_uci, rec_san, source, reason, verified = rec.chosen_uci, rec.chosen_san, rec.chosen_source, \
            rec.reason, rec.verified

    # The engine's punishment of the played move: best line after it.
    board = chess.Board(lk.fen)
    board.push_uci(lk.played)
    refutation: list[str] = []
    if lk.kind != "gambit_note" and not board.is_game_over():
        refutation = engine.evaluate(board.fen(), depth=depth).lines[0].pv_san[:4]

    allowed = verify.allowed_moves_for(lk.fen, [m for m in (lk.played, rec_uci) if m])
    allowed |= verify.allowed_line(board.fen(), engine.evaluate(board.fen(), depth=depth).lines[0].pv_uci[:4]) \
        if refutation else set()

    docs: list[RetrievedDoc] = []
    if use_rag:
        query = f"{lk.opening_name} {played_san} {rec_san} plan typical mistake"
        docs = rag.retrieve(query, eco=lk.opening_eco or None, k=4)
    return LeakFacts(leak=lk, played_san=played_san, rec_uci=rec_uci, rec_san=rec_san, rec_source=source,
                     rec_reason=reason, rec_verified=verified, refutation_san=refutation, allowed_moves=allowed,
                     docs=docs, master_games=rag.master_games_for(lk.opening_eco, lk.opening_name))


def template_explanation(f: LeakFacts) -> LeakExplanation:
    """Condition 0: engine facts in fixed sentences, no LLM."""
    lk = f.leak
    if lk.kind == "gambit_note":
        return LeakExplanation(explanation=lk.note, plan="", memory_aid="")
    times = f"{lk.frequency} time{'s' if lk.frequency != 1 else ''}"
    expl = (f"You played {f.played_san} here {times}. Stockfish rates it {lk.avg_loss / 100:.2f} pawns worse "
            f"than the best continuation")
    if f.refutation_san:
        expl += f"; the engine answers with {' '.join(f.refutation_san[:2])}"
    expl += "."
    if lk.kind == "gambit_deviation":
        expl = f"Inside the gambit, {f.played_san} gives back the compensation ({lk.avg_loss / 100:.2f} pawns " \
               f"worse than the best gambit-keeping move)."
    elif lk.kind == "defender_trap":
        expl = f"Against the gambit, {f.played_san} falls into a known trap and loses {lk.avg_loss / 100:.2f} pawns."
    label = {"master": "master choice", "engine": "engine choice"}.get(f.rec_source or "", "")
    plan = f"Play {f.rec_san} instead ({label}: {f.rec_reason})." if f.rec_san else ""
    cites: list[str] = []
    if f.docs:
        # Cite by id only: document titles can contain move text ("...c5") that was not verified here.
        plan += f" Background reading: [{f.docs[0].id}]."
        cites = [f.docs[0].id]
    return LeakExplanation(explanation=expl, plan=plan, memory_aid="", citations=cites)


def _guard_reasons(f: LeakFacts, out: LeakExplanation) -> list[str]:
    text = " ".join([out.explanation, out.plan, out.memory_aid])
    reasons = verify.verify_text_moves(text, f.allowed_moves).reasons
    reasons += verify.verify_citations(out.citations, f.docs).reasons
    reasons += verify.verify_citations(text, f.docs).reasons
    return reasons


def explain(f: LeakFacts, mode: str = "full", rating: int | None = None) -> tuple[LeakExplanation, str]:
    """Return (explanation, generated_by). Falls back to the template when the LLM is off or fails the guard."""
    if mode == "template" or not client.is_available():
        return template_explanation(f), "template"
    docs = [{"id": d.id, "title": d.citation.title, "text": d.text} for d in f.docs] if mode != "llm" else []
    builder = prompts.gambit_note if f.leak.kind == "gambit_note" else prompts.leak_diagnosis
    prompt = builder(f.as_dict(), docs)
    check = (lambda o: _guard_reasons(f, o)) if mode == "full" else None
    try:
        # Guard failures are fed back once (max_retries=1), then the item falls back.
        out = client.generate_structured(prompt, LeakExplanation, system=prompts.system_prompt(rating),
                                         name=f"leak_diagnosis:{mode}", max_retries=1, extra_check=check)
        return out, "llm"
    except (ValueError, client.LLMRefused, client.LLMError):
        if mode == "full":
            return template_explanation(f), "template"
        raise


def build_item(lk: LeakOut, mode: str = "full", depth: int | None = None, rating: int | None = None
               ) -> GapReportItem:
    f = gather_facts(lk, depth=depth, use_rag=mode != "llm")
    out, by = explain(f, mode, rating)
    cites = {d.id: d.citation for d in f.docs}
    return GapReportItem(
        opening=lk.opening_name, color=lk.color, kind=lk.kind, position_fen=lk.fen, played=lk.played,  # type: ignore[arg-type]
        played_san=f.played_san, recommended=f.rec_uci, recommended_san=f.rec_san,
        recommended_source=f.rec_source, reason=f.rec_reason, eval_loss=lk.avg_loss,  # type: ignore[arg-type]
        frequency=lk.frequency, explanation=out.explanation, plan=out.plan, memory_aid=out.memory_aid,
        master_games=f.master_games, citations=[cites[c] for c in out.citations if c in cites],
        verified=f.rec_verified and (mode in ("full", "template") or by == "template"),
        is_gambit_note=lk.kind == "gambit_note",
    )


def build_gap_report(leaks: list[LeakOut], mode: str = "full", depth: int | None = None, rating: int | None = None,
                     top: int = 10) -> GapReport:
    real = [lk for lk in leaks if lk.kind != "gambit_note"][:top]
    notes = [lk for lk in leaks if lk.kind == "gambit_note"]
    items = [build_item(lk, mode, depth, rating) for lk in real + notes]
    by_llm = mode != "template" and client.is_available()
    return GapReport(leaks=items, generated_by="llm" if by_llm else "template")


# ---------------------------------------------------------------------------
# Deviation detail view (spec 8.8 "Detail view")
# ---------------------------------------------------------------------------


def explain_deviation(dev, opening: str = "", eco: str | None = None, rating: int | None = None,
                      depth: int | None = None) -> tuple[LeakExplanation, list[RetrievedDoc], str]:
    """Guarded explanation of one repertoire deviation (template when the LLM is off or fails the guard)."""
    board = chess.Board(dev.node_fen if len(dev.node_fen.split()) >= 6 else dev.node_fen + " 0 1")
    fen = board.fen()
    allowed = verify.allowed_moves_for(fen, [m for m in (dev.played_move, dev.repertoire_move,
                                                         dev.recommended_move) if m])
    after = board.copy()
    after.push_uci(dev.played_move)
    refutation: list[str] = []
    if not after.is_game_over():
        top = engine.evaluate(after.fen(), depth=depth)
        refutation = top.lines[0].pv_san[:4]
        allowed |= verify.allowed_line(after.fen(), top.lines[0].pv_uci[:4])
    docs = rag.retrieve(f"{opening} {dev.played_san} {dev.repertoire_san} {dev.recommended_san} plan", eco=eco, k=4)
    facts = {"opening": opening, "classification": dev.classification, "played_san": dev.played_san,
             "repertoire_san": dev.repertoire_san, "recommended_san": dev.recommended_san,
             "recommended_source": dev.recommended_source, "reason": dev.reason, "games": dev.games_count,
             "results": dev.results, "avg_loss_pawns": round(dev.avg_eval_loss / 100, 2),
             "engine_line_after_played": refutation}

    def template() -> LeakExplanation:
        verdict = {"mistake": "loses ground", "inaccuracy": "is slightly worse", "harmless": "is about equal",
                   "better": "is actually better"}.get(dev.classification, "differs")
        text = (f"In {dev.games_count} game(s) you played {dev.played_san} instead of your repertoire move "
                f"{dev.repertoire_san}; Stockfish says it {verdict} ({dev.avg_eval_loss / 100:.2f} pawns).")
        plan = f"Recommended: {dev.recommended_san} ({dev.recommended_source}). {dev.reason}"
        if docs:
            plan += f" Background reading: [{docs[0].id}]."
        return LeakExplanation(explanation=text, plan=plan, citations=[docs[0].id] if docs else [])

    if not client.is_available():
        return template(), docs, "template"

    def check(o: LeakExplanation) -> list[str]:
        text = " ".join([o.explanation, o.plan, o.memory_aid])
        return (verify.verify_text_moves(text, allowed).reasons + verify.verify_citations(o.citations, docs).reasons
                + verify.verify_citations(text, docs).reasons)

    prompt = prompts.deviation_explanation(facts, [{"id": d.id, "title": d.citation.title, "text": d.text}
                                                   for d in docs])
    try:
        out = client.generate_structured(prompt, LeakExplanation, system=prompts.system_prompt(rating),
                                         name="deviation_explanation", max_retries=1, extra_check=check)
        return out, docs, "llm"
    except (ValueError, client.LLMRefused, client.LLMError):
        return template(), docs, "template"
