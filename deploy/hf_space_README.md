---
title: SecondMind
emoji: ♞
colorFrom: green
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
short_description: Opening-repertoire and preparation agent for club players
---

# SecondMind

A personalized opening-repertoire and preparation agent for club chess players. It reads your
Lichess and Chess.com games, compares them with your repertoire, ranks where you leave it, explains
mistakes with cited theory, scouts opponents and trains you with engine-verified quizzes.

Every move, evaluation and citation is checked by code (python-chess + Stockfish) before you see it.
Explanations come from an open-weights model on Groq's free tier; live analysis runs Stockfish in
your browser.

Source code and documentation: see the GitHub repository.

**Note:** this free Space stores data in a local SQLite file, which is reset when the Space restarts.
