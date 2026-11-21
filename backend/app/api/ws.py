"""Live Stockfish analysis over WebSocket (spec 5.1.3, 8.9).

Protocol: the client sends ``{"fen": "..."}``; the server streams
``{"type": "info", depth, cp_white, mate, lines: [...], masters: [...]}`` updates.
Sending a new FEN cancels the previous analysis; disconnecting stops it. Each
connection gets its own engine process (see ``engine.analysis_stream``), so
live analysis never blocks batch jobs.
"""

from __future__ import annotations

import asyncio
import contextlib

import chess
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.tools import engine, masters

router = APIRouter()


async def _stream(ws: WebSocket, fen: str) -> None:
    stats = masters.master_moves(fen)
    top_masters = [{"san": m.san, "uci": m.uci, "games": m.games} for m in stats.moves[:5]]
    async for update in engine.analysis_stream(fen, multipv=3, max_depth=24):
        await ws.send_json({"type": "info", "fen": fen, **update, "masters": top_masters,
                            "masters_source": stats.source})
    await ws.send_json({"type": "done", "fen": fen})


@router.websocket("/ws/analysis")
async def ws_analysis(ws: WebSocket) -> None:
    await ws.accept()
    task: asyncio.Task | None = None
    try:
        while True:
            msg = await ws.receive_json()
            fen = msg.get("fen", "")
            try:
                chess.Board(fen)
            except ValueError:
                await ws.send_json({"type": "error", "message": "invalid FEN"})
                continue
            if task and not task.done():
                task.cancel()  # a new position cancels the previous analysis
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            if not engine.is_available():
                await ws.send_json({"type": "error", "message": "Stockfish is not configured"})
                continue
            task = asyncio.create_task(_stream(ws, fen))
    except WebSocketDisconnect:
        pass
    finally:
        if task and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
