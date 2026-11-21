import { useEffect, useRef, useState } from "react";
import { analysisSocketUrl } from "../api.js";

// Live Stockfish panel (spec 8.9): evaluation bar (White's view), top 3 lines in SAN,
// search depth, and master statistics for the current position. A new FEN cancels
// the previous analysis on the server.
export default function EnginePanel({ fen, playerColor = "white" }) {
  const [info, setInfo] = useState(null);
  const [error, setError] = useState(null);
  const wsRef = useRef(null);
  const fenRef = useRef(fen);

  useEffect(() => {
    const ws = new WebSocket(analysisSocketUrl());
    let closedByUs = false; // StrictMode mounts twice in dev; ignore errors from sockets we closed
    wsRef.current = ws;
    ws.onopen = () => ws.send(JSON.stringify({ fen: fenRef.current }));
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.type === "info" && msg.fen === fenRef.current) {
        setInfo(msg);
        setError(null);
      }
      if (msg.type === "error") setError(msg.message);
    };
    ws.onerror = () => {
      if (!closedByUs) setError("Live analysis unavailable (is the backend running?)");
    };
    return () => {
      closedByUs = true;
      ws.close();
    };
  }, []);

  useEffect(() => {
    fenRef.current = fen;
    setInfo(null);
    setError(null);
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ fen }));
  }, [fen]);

  const cpWhite = info ? info.cp_white : 0;
  // Map +-600 cp onto the bar; mate scores saturate it.
  const whiteShare = Math.max(2, Math.min(98, 50 + cpWhite / 12));
  const fmt = (cp, mate) => (mate != null ? `M${mate}` : (cp / 100 >= 0 ? "+" : "") + (cp / 100).toFixed(2));
  const playerCp = playerColor === "white" ? cpWhite : -cpWhite;

  return (
    <div className="engine">
      <div className="evalbar" title="Evaluation (White's view)">
        <div className="evalbar-white" style={{ height: `${whiteShare}%` }} />
      </div>
      <div className="engine-body">
        <div className="engine-head">
          <strong>Stockfish</strong>
          {info ? <span> depth {info.depth} · {fmt(info.cp_white, info.mate)} (White)</span> : <span> thinking…</span>}
          <span className="badge engine-badge">engine-verified</span>
        </div>
        {error && <div className="error">{error}</div>}
        {info && (
          <>
            <p className="muted">
              For you ({playerColor}): {playerCp >= 0 ? "+" : ""}
              {(playerCp / 100).toFixed(2)} pawns
            </p>
            <ol className="lines">
              {info.lines.map((l, i) => (
                <li key={i}>
                  <code>{fmt(l.cp_white, l.mate)}</code> {l.san_pv.join(" ")}
                </li>
              ))}
            </ol>
            <div className="masters">
              <strong>Masters</strong> <span className="muted">({info.masters_source})</span>
              {info.masters.length === 0 && <span className="muted"> no master data</span>}
              {info.masters.map((m) => (
                <span key={m.uci} className="chip">
                  {m.san} <small>{m.games}</small>
                </span>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
