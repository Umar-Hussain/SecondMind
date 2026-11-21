import { useEffect, useRef, useState } from "react";
import { analysisSocketUrl, api } from "../api.js";
import { browserEngineSupported, createBrowserEngine } from "../engine/browserEngine.js";

// Live Stockfish panel (spec 8.9): evaluation bar (White's view), top 3 lines in SAN,
// search depth, and master statistics for the current position.
//
// The engine runs in the visitor's browser (Stockfish WebAssembly) so the free server
// only does batch analysis. If WebAssembly is unavailable it falls back to the
// server's WebSocket stream. A new FEN cancels the previous search either way.
export default function EnginePanel({ fen, playerColor = "white", hideMasters = false }) {
  const [info, setInfo] = useState(null);
  const [masters, setMasters] = useState(null);
  const [error, setError] = useState(null);
  const [where, setWhere] = useState(browserEngineSupported() ? "browser" : "server");
  const engineRef = useRef(null);
  const wsRef = useRef(null);
  const fenRef = useRef(fen);

  // Start one engine per panel: browser worker first, server WebSocket as fallback.
  useEffect(() => {
    let closedByUs = false; // StrictMode mounts twice in dev; ignore errors from things we closed
    if (where === "browser") {
      try {
        const eng = createBrowserEngine({ multipv: 3, maxDepth: 22 });
        engineRef.current = eng;
        eng.analyse(fenRef.current, (u) => { setInfo(u); setError(null); });
        return () => { closedByUs = true; eng.terminate(); };
      } catch {
        setWhere("server");
        return undefined;
      }
    }
    const ws = new WebSocket(analysisSocketUrl());
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
  }, [where]);

  // New position: restart the search and fetch master statistics from the server.
  useEffect(() => {
    fenRef.current = fen;
    setInfo(null);
    setError(null);
    if (where === "browser" && engineRef.current) {
      engineRef.current.analyse(fen, (u) => { if (fenRef.current === fen) setInfo(u); });
    } else {
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ fen }));
    }
    let cancelled = false;
    if (hideMasters) return undefined;
    api.get(`/masters?fen=${encodeURIComponent(fen)}`)
      .then((m) => { if (!cancelled) setMasters(m); })
      .catch(() => { if (!cancelled) setMasters(null); });
    return () => { cancelled = true; };
  }, [fen, where]);

  const masterMoves = masters ? masters.moves.slice(0, 5) : info?.masters || [];
  const masterSource = masters ? masters.source : info?.masters_source;

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
          <span className="muted"> · runs in your {where === "browser" ? "browser" : "server"}</span>
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
          </>
        )}
        {!hideMasters && <div className="masters">
          <strong>Masters</strong> {masterSource && <span className="muted">({masterSource})</span>}
          {masterMoves.length === 0 && <span className="muted"> no master data</span>}
          {masterMoves.map((m) => (
            <span key={m.uci} className="chip">
              {m.san} <small>{m.games}</small>
            </span>
          ))}
        </div>}
      </div>
    </div>
  );
}
