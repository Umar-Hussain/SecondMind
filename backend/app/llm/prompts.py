"""Prompt templates (spec 9.2, Phase 12).

Every prompt:

* states the role — a chess *second* explaining to a club player;
* receives only verified facts (FENs, moves, evaluations, retrieved passages
  with ids, the recommendation source and its reason);
* includes few-shot examples;
* asks for short reasoning before the answer on diagnosis tasks;
* forbids mentioning any move or source that was not provided.

Prompts are versioned with ``PROMPT_VERSION`` so evaluation runs can record
which version produced which numbers.
"""

from __future__ import annotations

import json

PROMPT_VERSION = "2026-11-21.1"

SYSTEM_SECOND = """You are SecondMind, a chess second preparing openings for a club player (about {rating} Elo).
You explain plans in plain language, like a coach talking to a student.

Hard rules:
1. Only mention moves that appear in the FACTS block. Never invent a move, a variation or an evaluation.
2. Only cite sources by their id in square brackets, e.g. [idea-caro-advance], and only ids listed under SOURCES.
3. If the facts are not enough to explain something, say so briefly instead of guessing.
4. Evaluations are in pawns from the player's point of view (+0.50 means the player is half a pawn better).
5. Adapt the wording to the player's level: {level_hint}"""

LEVEL_HINTS = {
    "beginner": "use simple words, one idea at a time, no long variations.",
    "intermediate": "name the key plan and the key square or pawn break; short lines are fine.",
    "advanced": "you may discuss pawn structures and typical manoeuvres concisely.",
}


def level_for(rating: int | None) -> str:
    if rating is None or rating < 1300:
        return "beginner"
    if rating < 1700:
        return "intermediate"
    return "advanced"


def system_prompt(rating: int | None = None) -> str:
    lvl = level_for(rating)
    return SYSTEM_SECOND.format(rating=rating or 1500, level_hint=LEVEL_HINTS[lvl])


def _sources_block(docs: list[dict]) -> str:
    if not docs:
        return "SOURCES: none"
    lines = [f"[{d['id']}] {d['title']}: {d['text']}" for d in docs]
    return "SOURCES:\n" + "\n".join(lines)


def _facts_block(facts: dict) -> str:
    return "FACTS:\n" + json.dumps(facts, indent=1, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Few-shot examples (written for this project; they illustrate format only)
# ---------------------------------------------------------------------------

LEAK_FEWSHOT = """EXAMPLE 1
FACTS: {"opening": "Ruy Lopez", "played_san": "Nxe5", "recommended_san": "Ba4", "recommended_source": "master",
 "reason": "Ba4: played in 80% of master games, 5 cp from the best engine move", "eval_loss_pawns": 6.6,
 "frequency": 3, "engine_line_after_played": ["Nxe5", "Nxe5"]}
SOURCES: [idea-ruy-morphy] ...
ANSWER: {"reasoning": "The bishop on b5 is attacked by a6, so grabbing e5 ignores the threat; after Nxe5 Nxe5 a piece is lost.",
 "explanation": "Nxe5 grabs a pawn while your bishop is still attacked. After Nxe5 you have given a knight for a pawn.",
 "plan": "Retreat with Ba4, keep the pin on c6, castle and prepare c3 and d4 [idea-ruy-morphy].",
 "memory_aid": "Bishop attacked? Answer the threat before grabbing pawns.", "citations": ["idea-ruy-morphy"]}

EXAMPLE 2
FACTS: {"opening": "Caro-Kann Defence: Advance Variation", "played_san": "Bg4", "recommended_san": "e6",
 "recommended_source": "repertoire", "eval_loss_pawns": 0.4, "frequency": 2, "results": {"draw": 1, "loss": 1}}
SOURCES: [idea-caro-advance] ...
ANSWER: {"reasoning": "Bg4 moves the bishop twice; e6 completes the setup and prepares c5.",
 "explanation": "Bg4 spends a tempo on the same bishop and lets White gain the bishop pair after h3.",
 "plan": "Play e6 and then c5 to hit the base of White's pawn chain [idea-caro-advance].",
 "memory_aid": "Bishop out, then e6 and c5.", "citations": ["idea-caro-advance"]}"""


def leak_diagnosis(facts: dict, docs: list[dict]) -> str:
    """Why the player's move fails, the plan behind the recommended move, a memory aid."""
    return f"""Diagnose one recurring opening problem of the player.
Think briefly first (field "reasoning", 1-2 sentences), then answer.
Return JSON with fields: reasoning, explanation (<= 3 sentences), plan (<= 3 sentences),
memory_aid (one line), citations (list of source ids you used).
Never name a move that is not in FACTS (played_san, recommended_san, engine lines).

{LEAK_FEWSHOT}

NOW THE REAL CASE
{_facts_block(facts)}
{_sources_block(docs)}
ANSWER:"""


def gambit_note(facts: dict, docs: list[dict]) -> str:
    return f"""The player deliberately plays a gambit. Write a neutral two-sentence note: what the gambit's
compensation is and what the facts say about its objective evaluation and the player's practical results.
Do NOT advise the player to stop playing it. Return JSON with fields: reasoning, explanation, plan,
memory_aid, citations.

EXAMPLE
FACTS: {{"gambit": "Englund Gambit", "objective_eval_pawns_white": 2.24, "player_score": 0.0, "games": 1}}
ANSWER: {{"reasoning": "Objectively dubious, but a practical choice.", "explanation": "The Englund gives a pawn for quick
piece play and traps; engines rate it clearly better for White.", "plan": "If you keep it, know the main trap lines
by heart [idea-englund].", "memory_aid": "Traps are your compensation.", "citations": ["idea-englund"]}}

NOW THE REAL CASE
{_facts_block(facts)}
{_sources_block(docs)}
ANSWER:"""


def deviation_explanation(facts: dict, docs: list[dict]) -> str:
    return f"""The player keeps leaving their own repertoire in the position below. Explain what the
played move does wrong (or right, if classification is "better"/"harmless") compared with the repertoire move,
and the plan behind the recommended move. Same JSON fields and rules as a leak diagnosis.

{LEAK_FEWSHOT}

NOW THE REAL CASE
{_facts_block(facts)}
{_sources_block(docs)}
ANSWER:"""


def quiz_explanation(facts: dict, docs: list[dict]) -> str:
    return f"""Explain in two sentences why the correct quiz move is good in this position, using only the
facts and sources. Return JSON with fields: reasoning, explanation, plan, memory_aid, citations.

{_facts_block(facts)}
{_sources_block(docs)}
ANSWER:"""


def opponent_summary(facts: dict) -> str:
    return f"""Summarize an opponent's opening habits for a pre-game briefing in 3-5 short bullet points.
Use only the statistics in FACTS (frequencies, scores, repeated lines, clock usage). Mention moves only
if they appear in FACTS. Return plain text bullets starting with "- ".

EXAMPLE
FACTS: {{"as_black_vs_e4": [{{"opening": "Caro-Kann Defence", "games": 7, "score": 0.29}}], "time_trouble_rate": 0.4}}
ANSWER:
- Answers 1.e4 with the Caro-Kann almost every time (7 games) and scores only 29% with it.
- Often gets into time trouble (40% of games): keep the position complex.

NOW THE REAL CASE
{_facts_block(facts)}
ANSWER:"""


def extra_line_explanation(facts: dict, docs: list[dict]) -> str:
    return f"""Explain the plan behind this short preparation line against a specific opponent in two or three
sentences, grounded in the sources. Return JSON with fields: reasoning, explanation, plan, memory_aid, citations.

{_facts_block(facts)}
{_sources_block(docs)}
ANSWER:"""


def novelty_explanation(facts: dict, docs: list[dict]) -> str:
    return f"""This rare but engine-sound move is a surprise weapon against the opponent's favourite line.
Explain the idea in two sentences. Return JSON with fields: reasoning, explanation, plan, memory_aid, citations.

{_facts_block(facts)}
{_sources_block(docs)}
ANSWER:"""


def post_game_review(facts: dict, docs: list[dict]) -> str:
    return f"""Review the opening of a game the player just finished against the prepared line.
Say who left the preparation first, where the evaluation swung, and what to remember next time.
Return JSON with fields: reasoning, explanation, plan, memory_aid, citations.

{_facts_block(facts)}
{_sources_block(docs)}
ANSWER:"""


def briefing_key_ideas(facts: dict, docs: list[dict]) -> str:
    return f"""Write 3 key ideas for the player's next game, one sentence each, using only FACTS and SOURCES.
Return JSON with fields: reasoning, explanation (the 3 ideas separated by newlines), plan, memory_aid, citations.

{_facts_block(facts)}
{_sources_block(docs)}
ANSWER:"""
