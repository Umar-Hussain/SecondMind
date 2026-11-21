"""Delivery: Telegram bot and calendar (.ics) reminders (spec 11.3, 11.4, Phase 17).

All outgoing content is built from already-verified objects (quizzes, stored
leaks, briefings). The bot runs as its own process::

    python -m app.services.delivery          # needs TELEGRAM_BOT_TOKEN

Commands: /start <lichess> [chesscom], /leaks, /deviations, /quiz, /scout <user>, /briefing.
A quiz answer is a move in SAN or UCI; it is graded and SM-2 is updated.
"""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

import chess
import chess.svg
from ics import Calendar, Event
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal, init_db
from app.models import Briefing as BriefingRow, Leak, Quiz, Repertoire, User
from app.tools import quiz as quiz_tools, srs
from app.tools.pgn_utils import uci_to_san
from app.tools.verify import parse_move

WEB_BASE = "http://localhost:5173"


# --- Calendar ---------------------------------------------------------------------


def briefing_ics(opponent: str, briefing_id: int, game_time: datetime, lead_minutes: int = 60) -> str:
    """One event for the briefing (an hour before the game) and one for the game."""
    if game_time.tzinfo is None:
        game_time = game_time.replace(tzinfo=timezone.utc)
    cal = Calendar()
    prep = Event(name=f"Prep vs {opponent} (RepertoireAI briefing)", begin=game_time - timedelta(minutes=lead_minutes),
                 duration=timedelta(minutes=30),
                 description=f"Open your briefing: {WEB_BASE}/scout?briefing={briefing_id}")
    prep.url = f"{WEB_BASE}/scout?briefing={briefing_id}"
    game = Event(name=f"Game vs {opponent}", begin=game_time, duration=timedelta(hours=1))
    cal.events.add(prep)
    cal.events.add(game)
    return cal.serialize()


def review_session_ics(user_id: int, when: datetime, quizzes_due: int) -> str:
    cal = Calendar()
    cal.events.add(Event(name=f"RepertoireAI review ({quizzes_due} quizzes)", begin=when,
                         duration=timedelta(minutes=15), description=f"{WEB_BASE}/train?user={user_id}"))
    return cal.serialize()


# --- Board images -------------------------------------------------------------------


def board_png(fen: str, flipped: bool = False) -> bytes | None:
    """PNG via cairosvg when installed; otherwise None and the bot sends a web link."""
    svg = chess.svg.board(chess.Board(fen), flipped=flipped, size=360)
    try:  # optional dependency
        import cairosvg  # type: ignore

        return cairosvg.svg2png(bytestring=svg.encode())
    except Exception:
        return None


def board_link(fen: str) -> str:
    return f"https://lichess.org/analysis/standard/{fen.replace(' ', '_')}"


# --- Message builders (pure, testable) -------------------------------------------------


def leaks_text(user_id: int) -> str:
    with SessionLocal() as s:
        rows = s.scalars(select(Leak).where(Leak.user_id == user_id, Leak.kind != "gambit_note")).all()
    rows = sorted(rows, key=lambda lk: -lk.frequency * max(lk.eval_loss_cp, 1))[:5]
    if not rows:
        return "No open leaks yet. Run an analysis in the web app first."
    lines = ["Your top opening leaks:"]
    for i, lk in enumerate(rows, 1):
        rec = f" -> play {uci_to_san(lk.fen_before, lk.theory_move)}" if lk.theory_move else ""
        lines.append(f"{i}. {lk.opening_name}: {uci_to_san(lk.fen_before, lk.played_move)} x{lk.frequency} "
                     f"(-{lk.eval_loss_cp / 100:.1f}){rec}")
    return "\n".join(lines)


def grade_text_answer(user_id: int, quiz_id: int, answer: str) -> str:
    with SessionLocal() as s:
        q = s.get(Quiz, quiz_id)
        if q is None:
            return "That quiz no longer exists."
        move = parse_move(chess.Board(q.fen), answer)
        if move is None:
            return f"'{answer}' is not a legal move here. Try again."
        ok = quiz_tools.check_answer(q, move.uci())
        review = srs.grade_review(s, quiz_id, user_id, 5 if ok else 1)
        best = uci_to_san(q.fen, q.correct_move_uci)
        head = "Correct!" if ok else f"Not quite. The answer is {best}."
        return f"{head} {q.explanation}\nNext review in {review.interval_days} day(s)."


# --- Telegram bot -------------------------------------------------------------------------


def run_bot() -> None:  # pragma: no cover - needs a live token
    from telegram import Update
    from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

    init_db()
    token = get_settings().telegram_bot_token
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set")

    def user_for(chat_id: int) -> User | None:
        with SessionLocal() as s:
            return s.scalars(select(User).where(User.telegram_chat_id == str(chat_id))).first()

    async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not ctx.args:
            await update.message.reply_text("Usage: /start <lichess_username> [chesscom_username]")
            return
        with SessionLocal() as s:
            u = s.scalars(select(User).where(User.lichess_username == ctx.args[0])).first() or User(
                lichess_username=ctx.args[0])
            if len(ctx.args) > 1:
                u.chesscom_username = ctx.args[1]
            u.telegram_chat_id = str(update.effective_chat.id)
            s.add(u)
            s.commit()
        await update.message.reply_text("Linked. Try /leaks, /deviations, /quiz or /scout <username>.")

    async def leaks(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        u = user_for(update.effective_chat.id)
        await update.message.reply_text(leaks_text(u.id) if u else "Use /start first.")

    async def deviations(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        from app.tools.deviations import load_deviations

        u = user_for(update.effective_chat.id)
        if not u:
            await update.message.reply_text("Use /start first.")
            return
        with SessionLocal() as s:
            lines = []
            for rep in s.scalars(select(Repertoire).where(Repertoire.user_id == u.id)):
                for d in load_deviations(s, rep.id, rep.color)[:3]:
                    lines.append(f"{rep.name}: {d.played_san} instead of {d.repertoire_san} "
                                 f"({d.games_count} games, {d.classification})")
        await update.message.reply_text("\n".join(lines) or "No deviations yet.")

    async def quiz_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        u = user_for(update.effective_chat.id)
        if not u:
            await update.message.reply_text("Use /start first.")
            return
        with SessionLocal() as s:
            due = srs.get_due(s, u.id, limit=1)
        if not due:
            await update.message.reply_text("No quizzes due. Well done!")
            return
        q = due[0]
        ctx.user_data["quiz_id"] = q.id
        png = board_png(q.fen, flipped=" b " in q.fen)
        caption = f"{q.question}\nReply with your move (e.g. Nf3).\n{board_link(q.fen)}"
        if png:
            await update.message.reply_photo(io.BytesIO(png), caption=caption)
        else:
            await update.message.reply_text(caption)

    async def answer(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        u = user_for(update.effective_chat.id)
        qid = ctx.user_data.get("quiz_id")
        if u and qid:
            await update.message.reply_text(grade_text_answer(u.id, qid, update.message.text.strip()))
            ctx.user_data.pop("quiz_id", None)

    async def scout_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        from app.services.briefing import prepare

        u = user_for(update.effective_chat.id)
        if not u or not ctx.args:
            await update.message.reply_text("Usage: /scout <lichess_username> (after /start)")
            return
        await update.message.reply_text("Scouting... this can take a minute.")
        with SessionLocal() as s:
            b, bid = prepare(s, u.id, ctx.args[0])
        text = [f"Briefing vs {b.opponent} (#{bid})"]
        text += [f"- {o['color']}: {o['line_san']} ({o['games']} games)" for o in b.likely_openings]
        text += [f"Extra line: {' '.join(x.moves_san)} (~{x.study_minutes} min)" for x in b.extra_lines]
        text += [f"Risk: {r}" for r in b.risks[:2]]
        await update.message.reply_text("\n".join(text))

    async def briefing_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        u = user_for(update.effective_chat.id)
        with SessionLocal() as s:
            row = s.scalars(select(BriefingRow).where(BriefingRow.user_id == (u.id if u else -1))
                            .order_by(BriefingRow.id.desc())).first()
        await update.message.reply_text(f"Latest briefing: {WEB_BASE}/scout?briefing={row.id}" if row
                                        else "No briefing yet. Use /scout <username>.")

    app = Application.builder().token(token).build()
    for name, fn in [("start", start), ("leaks", leaks), ("deviations", deviations), ("quiz", quiz_cmd),
                     ("scout", scout_cmd), ("briefing", briefing_cmd)]:
        app.add_handler(CommandHandler(name, fn))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, answer))
    app.run_polling()


if __name__ == "__main__":  # pragma: no cover
    run_bot()
