import { useCallback, useEffect, useMemo, useState } from "react";
import { Chess } from "chess.js";
import { api, fenKey } from "../api.js";
import Board, { arrow } from "../components/Board.jsx";
import EnginePanel from "../components/EnginePanel.jsx";

// Repertoire workspace, laid out like a Lichess study.
//   left   : the repertoire's lines ("chapters") and notes for the current position
//   centre : the board with the evaluation bar
//   right  : live Stockfish, the move list, moves stored here + master statistics, controls
// Library repertoires open read-only, with "Add to my repertoires".
export default function Workspace({ repId, user, onBack, onOpen }) {
  const [evaluation, setEvaluation] = useState(null); // live engine score for the board's bar
  const [tree, setTree] = useState(null);
  const [path, setPath] = useState([]); // [{uci, san}]
  const [flipped, setFlipped] = useState(false);
  const [masters, setMasters] = useState(null);
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => api.get(`/repertoires/${repId}/tree`).then(setTree).catch((e) => setError(e.message)), [repId]);
  useEffect(() => { setPath([]); load(); }, [load]);

  const nodes = useMemo(() => Object.fromEntries((tree?.nodes || []).map((n) => [n.fen_key, n])), [tree]);
  const game = useMemo(() => {
    const g = new Chess();
    path.forEach((m) => g.move({ from: m.uci.slice(0, 2), to: m.uci.slice(2, 4), promotion: m.uci[4] }));
    return g;
  }, [path]);
  const fen = game.fen();
  const node = nodes[fenKey(fen)];
  const editable = tree && !tree.is_library ? true : tree?.is_library && user.role === "admin";
  const userTurn = tree && (game.turn() === "w") === (tree.color === "white");

  useEffect(() => { setNote(node?.comment || ""); }, [node?.fen_key, node?.comment]);
  useEffect(() => {
    let cancelled = false;
    api.get(`/masters?fen=${encodeURIComponent(fen)}`).then((m) => !cancelled && setMasters(m)).catch(() => setMasters(null));
    return () => { cancelled = true; };
  }, [fen]);

  // Keyboard navigation like Lichess: left / right arrows step through the line.
  useEffect(() => {
    const onKey = (e) => {
      if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) return;
      if (e.key === "ArrowLeft") setPath((p) => p.slice(0, -1));
      if (e.key === "ArrowRight") document.getElementById("sv-next-btn")?.click();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const stored = node
    ? [
        ...(node.user_move ? [{ uci: node.user_move, san: node.user_move_san, kind: "main" }] : []),
        ...node.alternatives.map((a) => ({ ...a, kind: "alt" })),
        ...node.opponent_moves.map((a) => ({ ...a, kind: "opp" })),
      ]
    : [];
  const storedSet = new Set(stored.map((m) => m.uci));

  // The last move of the path is "unsaved" when its parent position does not store it.
  const last = path[path.length - 1];
  const parentFen = useMemo(() => {
    const g = new Chess();
    path.slice(0, -1).forEach((m) => g.move({ from: m.uci.slice(0, 2), to: m.uci.slice(2, 4), promotion: m.uci[4] }));
    return g.fen();
  }, [path]);
  const parentNode = nodes[fenKey(parentFen)];
  const parentMoves = parentNode ? [parentNode.user_move, ...parentNode.alternatives.map((a) => a.uci), ...parentNode.opponent_moves.map((a) => a.uci)] : [];
  const lastSaved = !last || parentMoves.includes(last.uci);

  function play(uci, san) {
    setMsg(null);
    setPath([...path, { uci, san }]);
  }

  function forward() {
    const next = stored[0];
    if (next) play(next.uci, next.san);
  }

  async function saveMove() {
    if (!last || lastSaved) return;
    const parentWhite = parentFen.split(" ")[1] === "w";
    const parentIsUser = parentWhite === (tree.color === "white");
    const body = { fen_key: fenKey(parentFen) };
    if (parentIsUser) {
      if (parentNode?.user_move) body.add_alternative = last.uci;
      else body.user_move = last.uci;
    } else body.add_opponent_move = last.uci;
    try {
      await api.patch(`/repertoires/${repId}/nodes`, body);
      setMsg(`Saved ${last.san} ${parentIsUser ? (body.user_move ? "as your move" : "as an alternative") : "as an opponent reply"}.`);
      await load();
    } catch (e) {
      setError(e.message);
    }
  }

  async function prune(uci, fromFen) {
    try {
      const res = await api.post(`/repertoires/${repId}/remove-move`, { fen_key: fenKey(fromFen), move: uci });
      setMsg(`Removed the move and ${res.removed_positions} position(s) after it.`);
      await load();
    } catch (e) {
      setError(e.message);
    }
  }

  async function saveNote() {
    if (!editable || !node || note === (node.comment || "")) return;
    await api.patch(`/repertoires/${repId}/nodes`, { fen_key: node.fen_key, comment: note });
    await load();
  }

  async function addToMine() {
    try {
      const copy = await api.post(`/library/${repId}/copy`, { name: tree.name });
      onOpen(copy.id);
    } catch (e) {
      setError(e.message);
    }
  }

  if (error && !tree) return <div className="alert">{error}</div>;
  if (!tree) return <p className="muted">Loading repertoire…</p>;

  const orientation = flipped ? (tree.color === "white" ? "black" : "white") : tree.color;
  const total = masters?.total_games || 0;
  const chapters = tree.preview?.chapters || [];
  // The chapter you are in: the most specific chapter whose opening moves match the current path.
  const pathUci = path.map((m) => m.uci);
  const activeChapter = chapters.reduce((best, c, i) => {
    const need = Math.min(Math.max(c.start, 1), c.uci.length);
    const fits = pathUci.length >= need && c.uci.slice(0, Math.min(pathUci.length, c.uci.length)).every((u, k) => u === pathUci[k]);
    return fits && (best < 0 || c.start > chapters[best].start) ? i : best;
  }, -1);
  const rows = [];
  for (let i = 0; i < path.length; i += 2) rows.push([i, path[i], path[i + 1]]);

  function openChapter(c) {
    const g = new Chess();
    const out = [];
    for (const u of c.uci.slice(0, Math.max(1, c.start))) {
      const mv = g.move({ from: u.slice(0, 2), to: u.slice(2, 4), promotion: u[4] });
      out.push({ uci: u, san: mv.san });
    }
    setMsg(null);
    setPath(out);
  }

  return (
    <section className="study-view fade-in">
      {/* ---------- left: chapters + notes ---------- */}
      <aside className="sv-left">
        <div className="sv-box">
          <div className="sv-tabs">
            <button className="ghost sv-back" onClick={onBack} title="Back to the list" aria-label="Back to the list">←</button>
            <span className="sv-tab active">{chapters.length} line{chapters.length === 1 ? "" : "s"}</span>
            <span className="sv-tab">{tree.nodes.length} positions</span>
          </div>
          <ol className="sv-chapters">
            {chapters.map((c, i) => (
              <li key={i} className={i === activeChapter ? "active" : ""}>
                <button onClick={() => openChapter(c)} title={c.moves}><span className="num">{i + 1}</span>{c.label}</button>
              </li>
            ))}
            {chapters.length === 0 && <li className="muted small pad">No lines yet. Play moves and press Save.</li>}
          </ol>
          {tree.is_library && user.role !== "admin" && <button className="sv-add" onClick={addToMine}>＋ Add to my repertoires</button>}
        </div>
        <div className="sv-box sv-notes">
          <div className="sv-box-title">
            <span>Notes</span>
            {!editable && <span className="tag">read-only</span>}
          </div>
          <textarea rows={7}
            placeholder={editable ? (node ? "Plans, traps and reminders for this position…" : "Save a move here to add notes.") : "No notes for this position."}
            value={note} onChange={(e) => setNote(e.target.value)} onBlur={saveNote} readOnly={!editable || !node} />
          {editable && node && note !== (node.comment || "") && <p className="muted small">Notes save when you click away.</p>}
        </div>
        <p className="sv-owner muted small">
          {tree.color === "white" ? "♔ White" : "♚ Black"} · {tree.name}
          {tree.is_library && <span className="tag library">library</span>}
        </p>
      </aside>

      {/* ---------- centre: board ---------- */}
      <div className="sv-board">
        <Board max={600} evaluation={evaluation} fen={fen} orientation={orientation} explore={false} highlight={last?.uci}
          arrows={stored.filter((m) => m.kind !== "opp").map((m) => arrow(m.uci, m.kind === "main" ? "rgba(21,120,27,.8)" : "rgba(21,120,27,.45)"))}
          onMove={(m) => !m.reset && play(m.uci, m.san)} />
        {!lastSaved && <p className="hint">{last.san} is not in this repertoire yet{editable ? ". Press Save to add it." : "."}</p>}
        {msg && <p className="ok small">{msg}</p>}
        {error && <div className="alert">{error}</div>}
      </div>

      {/* ---------- right: engine, move list, next moves, controls ---------- */}
      <aside className="sv-tools">
        <EnginePanel onInfo={setEvaluation} fen={fen} playerColor={tree.color} hideMasters compact />
        <div className="sv-moves">
          {rows.length === 0 && <p className="muted small pad">Starting position. Pick a line on the left, a move below, or play on the board.</p>}
          {rows.map(([i, w, b]) => (
            <div className="sv-row" key={i}>
              <span className="sv-num">{i / 2 + 1}</span>
              <button className={`sv-mv ${i === path.length - 1 ? "current" : ""}`} onClick={() => setPath(path.slice(0, i + 1))}>{w.san}</button>
              {b ? <button className={`sv-mv ${i + 1 === path.length - 1 ? "current" : ""}`} onClick={() => setPath(path.slice(0, i + 2))}>{b.san}</button> : <span />}
            </div>
          ))}
        </div>
        <div className="sv-next">
          <div className="sv-box-title"><span>{userTurn ? "Your move here" : "Opponent replies"}</span></div>
          <div className="sv-chips">
            {stored.map((m) => (
              <span key={m.kind + m.uci} className={`sv-chip ${m.kind}`}>
                <button onClick={() => play(m.uci, m.san)} title={m.kind === "main" ? "your main move" : m.kind === "alt" ? "alternative" : "opponent reply"}>
                  {m.san}{m.kind === "main" ? " ★" : ""}
                </button>
                {editable && <button className="x" title="Remove this move and everything after it" aria-label={`Remove ${m.san}`} onClick={() => prune(m.uci, fen)}>✕</button>}
              </span>
            ))}
            {stored.length === 0 && <span className="muted small">Nothing stored here.</span>}
          </div>
          <div className="sv-box-title"><span>Masters</span><span className="muted small">{masters?.source || ""}</span></div>
          <ul className="movelist masters-list">
            {(masters?.moves || []).slice(0, 5).map((m) => (
              <li key={m.uci}>
                <button className="move" onClick={() => play(m.uci, m.san)}>
                  <b>{m.san}</b>
                  <span className="bar-wrap"><span className="bar-fill" style={{ width: `${total ? (100 * m.games) / total : 0}%` }} /></span>
                  <span className="muted small">{total ? Math.round((100 * m.games) / total) : 0}%</span>
                  {storedSet.has(m.uci) && <span className="tag good">yours</span>}
                </button>
              </li>
            ))}
            {masters && masters.moves.length === 0 && <li className="muted small">No master games.</li>}
          </ul>
        </div>
        <div className="sv-controls">
          <button onClick={() => setPath([])} title="First move" aria-label="First move">⏮</button>
          <button onClick={() => setPath(path.slice(0, -1))} disabled={!path.length} title="Previous move (←)" aria-label="Previous move">❮</button>
          <button id="sv-next-btn" onClick={forward} disabled={!stored.length} title="Next move (→)" aria-label="Next move">❯</button>
          <button onClick={() => setFlipped(!flipped)} title="Flip board" aria-label="Flip board">⇅</button>
          {editable && <button className="save" onClick={saveMove} disabled={lastSaved} title="Save this move to the repertoire">Save</button>}
          {editable && last && lastSaved && (
            <button className="prune" title="Remove the last move and everything after it" aria-label="Remove the last move"
              onClick={() => { prune(last.uci, parentFen); setPath(path.slice(0, -1)); }}>✂</button>
          )}
        </div>
      </aside>
    </section>
  );
}
