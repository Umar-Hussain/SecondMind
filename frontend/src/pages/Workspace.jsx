import { useCallback, useEffect, useMemo, useState } from "react";
import { Chess } from "chess.js";
import { api, fenKey } from "../api.js";
import Board, { arrow } from "../components/Board.jsx";
import EnginePanel from "../components/EnginePanel.jsx";

// Three-column repertoire workspace.
//   left   : moves stored in this position + master statistics (click to play)
//   centre : board, move path, and the edit controls (save move, prune)
//   right  : repertoire info, notes for the position, live Stockfish
// Library repertoires open read-only, with "Add to my repertoires".
export default function Workspace({ repId, user, onBack, onOpen }) {
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

  return (
    <section className="workspace">
      <div className="ws-head">
        <button className="ghost" onClick={onBack}>← Back</button>
        <div>
          <h2>{tree.name}</h2>
          <span className="muted small">
            {tree.color === "white" ? "♔ White" : "♚ Black"} repertoire · {tree.nodes.length} positions
            {tree.is_library && <span className="tag library">library</span>}
            {tree.copied_from_id && <span className="tag">from library</span>}
          </span>
        </div>
        <div className="ws-actions">
          {tree.is_library && user.role !== "admin" && <button className="primary" onClick={addToMine}>＋ Add to my repertoires</button>}
          {!editable && <span className="tag">read-only</span>}
        </div>
      </div>

      <div className="ws-grid">
        {/* ---------- left: moves ---------- */}
        <aside className="panel">
          <div className="panel-title">Moves in this position</div>
          <p className="muted small">{userTurn ? "Your move" : "Opponent to move"} · click to play</p>
          {stored.length === 0 && <p className="muted small">Nothing stored here yet.{editable && " Play a move on the board and press Save move."}</p>}
          <ul className="movelist">
            {stored.map((m) => (
              <li key={m.kind + m.uci} className={m.kind}>
                <button className="move" onClick={() => play(m.uci, m.san)}>
                  <b>{m.san}</b>
                  <span className="muted small">{m.kind === "main" ? "your move ★" : m.kind === "alt" ? "alternative" : "opponent reply"}</span>
                </button>
                {editable && <button className="icon" title="Remove this move and everything after it" onClick={() => prune(m.uci, fen)}>✕</button>}
              </li>
            ))}
          </ul>
          <div className="panel-title spaced">Masters <span className="muted small">({masters?.source || "…"})</span></div>
          <ul className="movelist masters-list">
            {(masters?.moves || []).slice(0, 8).map((m) => (
              <li key={m.uci}>
                <button className="move" onClick={() => play(m.uci, m.san)}>
                  <b>{m.san}</b>
                  <span className="bar-wrap"><span className="bar-fill" style={{ width: `${total ? (100 * m.games) / total : 0}%` }} /></span>
                  <span className="muted small">{total ? Math.round((100 * m.games) / total) : 0}%</span>
                  {storedSet.has(m.uci) && <span className="tag good">in repertoire</span>}
                </button>
              </li>
            ))}
            {masters && masters.moves.length === 0 && <li className="muted small">No master games.</li>}
          </ul>
        </aside>

        {/* ---------- centre: board ---------- */}
        <div className="ws-center">
          <Board fen={fen} orientation={orientation} explore={false} highlight={last?.uci}
            arrows={stored.filter((m) => m.kind !== "opp").map((m) => arrow(m.uci, m.kind === "main" ? "rgba(54,146,231,.85)" : "rgba(54,146,231,.45)"))}
            onMove={(m) => !m.reset && play(m.uci, m.san)} />
          <div className="pathline">
            <button className="link" onClick={() => setPath([])}>start</button>
            {path.map((m, i) => (
              <button key={i} className={`link ${i === path.length - 1 ? "current" : ""}`} onClick={() => setPath(path.slice(0, i + 1))}>
                {i % 2 === 0 ? `${i / 2 + 1}.` : ""}{m.san}
              </button>
            ))}
          </div>
          <div className="controls">
            <button onClick={() => setPath([])} title="Start position">⏮ Start</button>
            <button onClick={() => setPath(path.slice(0, -1))} disabled={!path.length}>◀ Back</button>
            <button onClick={forward} disabled={!stored.length}>Forward ▶</button>
            <button onClick={() => setFlipped(!flipped)}>⇅ Flip</button>
            {editable && <button className="primary" onClick={saveMove} disabled={lastSaved}>💾 Save move</button>}
            {editable && last && lastSaved && <button className="danger" onClick={() => { prune(last.uci, parentFen); setPath(path.slice(0, -1)); }}>✂ Prune</button>}
          </div>
          {!lastSaved && <p className="hint">{last.san} is not in this repertoire yet{editable ? " — press Save move to add it." : "."}</p>}
          {msg && <p className="ok small">{msg}</p>}
          {error && <div className="alert">{error}</div>}
        </div>

        {/* ---------- right: info, notes, engine ---------- */}
        <aside className="panel">
          <div className="panel-title">{path.length ? `After ${Math.ceil(path.length / 2)}${path.length % 2 ? "." : "…"} ${last.san}` : "Starting position"}</div>
          {tree.description && <p className="muted small">{tree.description}</p>}
          <textarea rows={4} placeholder={editable ? "Notes for this position (plans, traps, reminders)…" : "No notes for this position."}
            value={note} onChange={(e) => setNote(e.target.value)} onBlur={saveNote} readOnly={!editable || !node} />
          {editable && node && note !== (node.comment || "") && <p className="muted small">Notes save when you click away.</p>}
          <EnginePanel fen={fen} playerColor={tree.color} hideMasters />
        </aside>
      </div>
    </section>
  );
}
