# RepertoireAI

Personalized opening-repertoire and preparation agent for club chess players (1000–2000 Elo).

RepertoireAI does the work of a human chess *second*: it reads your Lichess and Chess.com games,
compares them with your own repertoire, ranks where you keep leaving it, finds recurring opening
mistakes, retrieves master theory with citations, recommends practical moves (masters vs. Stockfish),
scouts your next opponent, and trains you with engine-verified quizzes and spaced repetition.

**Design rule:** deterministic tools (python-chess, Stockfish, master statistics, the scheduler)
produce every chess fact. The LLM diagnoses, explains and orchestrates. Nothing the model says about
a move, evaluation or source reaches the user unless the verification guard has checked it.

> Course project — AI-4009 Generative AI, Assignment 3 (Pure Product track).

## Status

Work in progress. See the commit history for the phase-by-phase build.
