"""Pre-game briefing (spec 5.7-5.10, Phase 15).

Combines the opponent profile with the player's repertoire and open leaks:

* likely openings (opponent's most frequent openings in the color they will have),
* recommended replies taken from the player's own repertoire tree, checked by
  the recommender; replies that coincide with the player's open leaks -> risks,
* extra lines outside the repertoire (``prep_lines.extra_line``), labelled as such,
* an optional engine-sound novelty in the opponent's most repeated line,
* quizzes for the extra lines, scheduled before the game.
"""

from __future__ import annotations

import chess
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Briefing as BriefingRow, Leak, PrepLine, Repertoire
from app.schemas import Briefing, ExtraLine
from app.tools import prep_lines, quiz, rag, srs
from app.tools.pgn_utils import fen_key, uci_to_san
from app.tools.repertoire import load_tree
from app.tools.scouting import scout


def _replies_from_repertoire(session: Session, user_id: int, player_color: str, line: list[str]) -> list[dict]:
    """Walk the opponent's line through the player's repertoire; collect the player's prepared moves."""
    reps = session.scalars(select(Repertoire).where(Repertoire.user_id == user_id, Repertoire.color == player_color,
                                                    Repertoire.status == "active")).all()
    out = []
    for rep in reps:
        tree = load_tree(session, rep.id)
        board = chess.Board()
        for u in line:
            node = tree.nodes.get(fen_key(board))
            if node is None:
                break
            if board.turn == tree.user_turn and node.user_move:
                out.append({"repertoire": rep.name, "fen": board.fen(), "move": node.user_move,
                            "san": uci_to_san(board.fen(), node.user_move), "source": "repertoire"})
            if chess.Move.from_uci(u) not in board.legal_moves:
                break
            board.push_uci(u)
    return out


def prepare(session: Session, user_id: int, opponent: str, platform: str = "lichess", depth: int | None = None,
            max_games: int = 300) -> tuple[Briefing, int]:
    profile = scout(session, opponent, platform, max_games=max_games, depth=depth)
    # The opponent's color in their repeated lines tells us which color we will face it with.
    repeated = profile["repeated_lines"]
    likely = [{"color": r["color"], "line_san": " ".join(r["moves_san"]), "games": r["games"], "score": r["score"]}
              for r in repeated[:3]]

    replies: list[dict] = []
    extra: list[ExtraLine] = []
    risks: list[str] = []
    leaks = session.scalars(select(Leak).where(Leak.user_id == user_id, Leak.status == "open")).all()
    leak_keys = {(lk.color, fen_key(lk.fen_before)) for lk in leaks if lk.kind != "gambit_note"}

    for r in repeated[:2]:
        player_color = "black" if r["color"] == "white" else "white"
        for rep in _replies_from_repertoire(session, user_id, player_color, r["moves"]):
            if (player_color, fen_key(rep["fen"])) in leak_keys:
                risks.append(f"You have an open leak in this line at {rep['san']} ({rep['repertoire']}).")
            replies.append(rep)
        line = prep_lines.extra_line(r["moves"], player_color, depth=depth)
        if line:
            first_opening = (profile["as_black"] if r["color"] == "black" else profile["as_white"])[:1]
            opening = first_opening[0]["opening"] if first_opening else ""
            eco = first_opening[0]["eco"] if first_opening else None
            line.goal = (f"Meet {opponent}'s favourite {opening} ({r['games']} games, they score "
                         f"{r['score']:.0%}) with sound master moves")
            line.master_games = prep_lines.cite_for(opening, eco)
            extra.append(line)

    for w in profile["weaknesses"][:2]:
        risks_or_targets = f"{opponent} often plays {w['san']} here ({w['games']} games), losing about " \
                           f"{w['loss_cp'] / 100:.1f} pawns: steer towards this position."
        risks.append(risks_or_targets)

    novelty = None
    if repeated:
        board = chess.Board()
        for u in repeated[0]["moves"][:6]:
            board.push_uci(u)
        novelty = prep_lines.find_novelty(board.fen(), depth=depth)

    ideas = []
    for r in repeated[:2]:
        docs = rag.retrieve(" ".join(r["moves_san"]) + " plan", k=1)
        if docs:
            ideas.append(f"{docs[0].citation.title} [{docs[0].id}]")
    briefing = Briefing(opponent=opponent, likely_openings=likely, recommended_replies=replies[:8],
                        extra_lines=extra, key_ideas=ideas, risks=risks, novelty=novelty,
                        citations=[c for x in extra for c in x.master_games])

    row = BriefingRow(user_id=user_id, opponent=opponent, content_json=briefing.model_dump(mode="json"))
    session.add(row)
    session.flush()
    for x in extra:
        session.add(PrepLine(briefing_id=row.id, opponent_line_fen=x.start_fen, moves_uci=x.moves, goal=x.goal,
                             eval_cp=x.final_eval_cp, master_games_json=[c.model_dump() for c in x.master_games],
                             study_minutes=x.study_minutes, in_repertoire=False))
    session.commit()
    _schedule_extra_line_quizzes(session, user_id, extra, depth)
    return briefing, row.id


def _schedule_extra_line_quizzes(session: Session, user_id: int, lines: list[ExtraLine], depth: int | None) -> None:
    """One quiz per player move in each extra line (only those that pass validity)."""
    for line in lines:
        board = chess.Board(line.start_fen)
        me = board.turn
        for u in line.moves:
            if board.turn == me:
                try:
                    draft = quiz.build_quiz(board.fen(), "white" if me else "black", depth=depth)
                except quiz.QuizRejected:
                    draft = None
                if draft and draft.correct == u:
                    q = quiz.save_quiz(session, draft)
                    srs.schedule(session, q.id, user_id)
            board.push_uci(u)
