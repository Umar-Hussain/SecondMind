import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Chess } from "chess.js";
import { api } from "../api.js";
import Board from "./Board.jsx";
import MoveBadge, { pawns } from "./MoveBadge.jsx";

// Split screen for one deviation (GET /compare):
//   left  : the move you played, then how your games usually went on;
//   right : your repertoire move and its prepared line, or (toggle) Stockfish's suggestion.
// Each side has its own board and ◀ ▶ buttons; every one of your moves carries a quality
// symbol (!! brilliant, ! great, ★ best, 📖 book, ?! inaccuracy, ? mistake, ?? blunder).
export default function CompareView({ repertoireId, fen, played, color }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [right, setRight] = useState("repertoire");
  const box = useRef(null);
  const [col, setCol] = useState(300);

  useEffect(() => {
    let live = true;
    setData(null);
    setError(null);
    api.get(`/compare?repertoire_id=${repertoireId}&fen=${encodeURIComponent(fen)}&played=${played}`)
      .then((d) => live && setData(d))
      .catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [repertoireId, fen, played]);

  // Two boards side by side: each takes half of the available width (full width on phones).
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return undefined;
    const fit = () => {
      const w = el.clientWidth;
      setCol(Math.floor(w < 560 ? Math.min(w - 8, 420) : (w - 24) / 2 - 8));
    };
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const rightData = right === "engine" ? data?.suggestion : data?.repertoire;
  return (
    <div className="cmp" ref={box}>
      {error && <div className="alert">{error}</div>}
      {!data && !error && (
        <div className="cmp-loading" style={{ minHeight: col + 120 }}>
          <span className="job-spin" aria-hidden="true" /> Comparing your move with your repertoire and Stockfish…
        </div>
      )}
      {data && (
        <>
          <Verdict data={data} />
          <div className="cmp-cols">
            <div>
              {/* keeps both boards level when the right column shows its toggle */}
              {data.suggestion && !data.same_as_repertoire && <div className="cmp-switch-spacer" aria-hidden="true" />}
              <Side title="What you play" tone="you" fen={fen} first={data.you} color={color} width={col}
              note={data.you.games ? `How your ${data.you.games} game${data.you.games === 1 ? "" : "s"} usually went on` : null} />
            </div>
            <div>
              {data.suggestion && !data.same_as_repertoire && (
                <div className="cmp-switch" role="tablist" aria-label="Compare with">
                  <button role="tab" aria-selected={right === "repertoire"} className={right === "repertoire" ? "on" : ""}
                    onClick={() => setRight("repertoire")}>Your repertoire</button>
                  <button role="tab" aria-selected={right === "engine"} className={right === "engine" ? "on" : ""}
                    onClick={() => setRight("engine")}>Stockfish suggests</button>
                </div>
              )}
              {rightData ? (
                <Side key={right} title={right === "engine" ? "Stockfish suggests" : "Your repertoire"} tone={right === "engine" ? "engine" : "rep"}
                  fen={fen} first={rightData} color={color} width={col}
                  note={right === "engine" ? "Best play for both sides from here" : "Your prepared line from here"} />
              ) : <p className="muted">Your repertoire has no move stored here.</p>}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// One sentence that sums the comparison up.
function Verdict({ data }) {
  const { you, repertoire: rep, suggestion: sug } = data;
  return (
    <div className="cmp-verdict">
      <span>You played <b>{you.san}</b> <MoveBadge a={you} withLabel /></span>
      {rep && <span>Repertoire: <b>{rep.san}</b> <MoveBadge a={rep} withLabel /></span>}
      {sug && !data.same_as_repertoire && sug.move !== you.move && (
        <span>Stockfish: <b>{sug.san}</b> <MoveBadge a={{ ...sug, kind: sug.kind === "book" ? "best" : sug.kind, symbol: sug.kind === "book" ? "★" : sug.symbol }} /></span>
      )}
      {data.same_as_repertoire && <span className="muted small">Stockfish agrees with your repertoire move.</span>}
    </div>
  );
}

function Side({ title, tone, fen, first, color, width, note }) {
  // Moves: the first move (annotated as a whole) and the line after it.
  const moves = [{ uci: first.move, san: first.san, fen_before: fen, kind: first.kind, symbol: first.symbol, label: first.label }, ...(first.line || [])];
  const [ply, setPly] = useState(1);
  const shown = moves.slice(0, ply);
  const g = new Chess(fen);
  shown.forEach((m) => g.move({ from: m.uci.slice(0, 2), to: m.uci.slice(2, 4), promotion: m.uci[4] }));
  const last = shown[shown.length - 1];

  return (
    <div className={`cmp-side ${tone}`}>
      <div className="cmp-head">
        <span className="cmp-title">{title}</span>
        <span className="cmp-move"><b>{first.san}</b> <MoveBadge a={first} /></span>
        <span className="cmp-eval" title="Evaluation after this move, from your side">{pawns(first.cp)}</span>
      </div>
      <Board fen={g.fen()} orientation={color} explore={false} width={width} highlight={last?.uci} canDrag={() => false} />
      <div className="cmp-nav">
        <button onClick={() => setPly(1)} disabled={ply <= 1} aria-label="First move">⏮</button>
        <button onClick={() => setPly(Math.max(1, ply - 1))} disabled={ply <= 1} aria-label="Previous move">❮</button>
        <button onClick={() => setPly(Math.min(moves.length, ply + 1))} disabled={ply >= moves.length} aria-label="Next move">❯</button>
        <button onClick={() => setPly(moves.length)} disabled={ply >= moves.length} aria-label="Last move">⏭</button>
      </div>
      {note && <p className="muted small cmp-note">{note}</p>}
      <div className="cmp-line">
        {moves.map((m, i) => {
          const [, turn, , , , full] = m.fen_before.split(" ");
          const num = turn === "w" ? `${full}.` : i === 0 ? `${full}…` : "";
          return (
            <button key={i} className={`cmp-mv ${i === ply - 1 ? "on" : ""}`} onClick={() => setPly(i + 1)}>
              {num && <span className="cmp-num">{num}</span>}{m.san}{m.kind && <MoveBadge a={m} />}
            </button>
          );
        })}
      </div>
    </div>
  );
}
