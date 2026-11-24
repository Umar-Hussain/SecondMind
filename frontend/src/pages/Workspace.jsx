import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Chess } from "chess.js";
import { api, fenKey } from "../api.js";
import Board, { arrow } from "../components/Board.jsx";
import EnginePanel from "../components/EnginePanel.jsx";
import MoveBadge, { pawns } from "../components/MoveBadge.jsx";
import { ARROW } from "../components/arrowColors.js";

// Repertoire workspace, laid out like a Lichess study.
//   left   : the repertoire's lines ("chapters") and notes for the current position
//   centre : the board with the evaluation bar
//   right  : live Stockfish, the move list, moves stored here + master statistics, controls
// Library repertoires open read-only, with "Add to my repertoires".
//
// Two modes:
//   practice : the app plays the opponent's moves from the repertoire, you answer with yours.
//              A wrong move is shown, then taken back; hints point at the right piece, then the move.
//   explore  : free browsing and editing (engine, masters, save / prune moves).
const PIECE = { p: "pawn", n: "knight", b: "bishop", r: "rook", q: "queen", k: "king" };
export default function Workspace({ repId, user, onBack, onOpen }) {
  const [evaluation, setEvaluation] = useState(null); // live engine score for the board's bar
  const [tree, setTree] = useState(null);
  const [path, setPath] = useState([]); // [{uci, san}]
  const [flipped, setFlipped] = useState(false);
  const [masters, setMasters] = useState(null);
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState(null);
  const [error, setError] = useState(null);
  const [mode, setMode] = useState(null); // "practice" | "explore", chosen once the tree loads
  const [bad, setBad] = useState(null); // a wrong practice move, shown briefly then taken back
  const [feedback, setFeedback] = useState(null); // {kind: good | bad | hint | done, text}
  const [hint, setHint] = useState(0); // 0 none, 1 which piece, 2 show the move
  const [score, setScore] = useState({ right: 0, wrong: 0 });
  const seen = useRef(new Map()); // position -> times practised, so later runs explore other replies

  const load = useCallback(() => api.get(`/repertoires/${repId}/tree`).then(setTree).catch((e) => setError(e.message)), [repId]);
  useEffect(() => { setPath([]); setMode(null); load(); }, [load]);
  useEffect(() => { if (tree && mode === null) setMode(tree.nodes.length ? "practice" : "explore"); }, [tree, mode]);

  const nodes = useMemo(() => Object.fromEntries((tree?.nodes || []).map((n) => [n.fen_key, n])), [tree]);
  const game = useMemo(() => {
    const g = new Chess();
    path.forEach((m) => g.move({ from: m.uci.slice(0, 2), to: m.uci.slice(2, 4), promotion: m.uci[4] }));
    return g;
  }, [path]);
  const fen = game.fen();
  const node = nodes[fenKey(fen)];
  const practice = mode === "practice";
  const shownFen = useMemo(() => {
    if (!bad) return fen;
    const g = new Chess(fen);
    g.move({ from: bad.uci.slice(0, 2), to: bad.uci.slice(2, 4), promotion: bad.uci[4] });
    return g.fen();
  }, [fen, bad]);
  const editable = tree && !tree.is_library ? true : tree?.is_library && user.role === "admin";
  const userTurn = tree && (game.turn() === "w") === (tree.color === "white");

  useEffect(() => { setNote(node?.comment || ""); }, [node?.fen_key, node?.comment]);
  useEffect(() => {
    let cancelled = false;
    api.get(`/masters?fen=${encodeURIComponent(fen)}`).then((m) => !cancelled && setMasters(m)).catch(() => setMasters(null));
    return () => { cancelled = true; };
  }, [fen]);

  const practiceRef = useRef(false);
  practiceRef.current = practice;

  // Keyboard navigation like Lichess: left / right arrows step through the line.
  useEffect(() => {
    const onKey = (e) => {
      if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) return;
      if (practiceRef.current) return; // in practice the app drives the opponent's moves
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

  // ---------------- practice mode ----------------
  const myMoves = node ? [node.user_move, ...node.alternatives.map((a) => a.uci)].filter(Boolean) : [];
  const theirMoves = node ? node.opponent_moves : [];
  const endText = path.length ? "End of this line. Well played!" : "Nothing to practise yet: this repertoire has no moves here.";

  // On the opponent's turn the app plays the stored reply practised least often, in the
  // repertoire's own order: the first run follows the main line exactly, later runs walk
  // through the side lines. On your turn it waits; with nothing stored the line is over.
  useEffect(() => {
    if (!practice || !tree || bad) return undefined;
    const here = fenKey(fen);
    seen.current.set(here, (seen.current.get(here) || 0) + 1);
    if (userTurn) {
      if (!myMoves.length) setFeedback({ kind: "done", text: endText });
      return undefined;
    }
    if (!theirMoves.length) {
      setFeedback({ kind: "done", text: endText });
      return undefined;
    }
    const visits = (m) => seen.current.get(keyAfter(fen, m.uci)) || 0;
    const pick = theirMoves.reduce((best, m) => (visits(m) < visits(best) ? m : best), theirMoves[0]);
    const t = setTimeout(() => setPath((p) => [...p, { uci: pick.uci, san: pick.san }]), path.length ? 550 : 350);
    return () => clearTimeout(t);
  }, [practice, fen, bad, tree]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => setHint(0), [fen]);

  function practiceMove(m) {
    if (bad || !userTurn || !myMoves.length) return;
    if (myMoves.includes(m.uci)) {
      setScore((x) => ({ ...x, right: x.right + 1 }));
      setFeedback({ kind: "good", badge: { kind: "book", symbol: "📖", label: "Book move" },
        text: m.uci === node.user_move ? `${m.san} is your repertoire move.` : `${m.san} is right (one of your alternatives).` });
      setPath([...path, { uci: m.uci, san: m.san }]);
    } else {
      setScore((x) => ({ ...x, wrong: x.wrong + 1 }));
      setFeedback({ kind: "bad", uci: m.uci, text: `${m.san} is not in your repertoire. Try again.` });
      setBad({ uci: m.uci, san: m.san });
      setTimeout(() => setBad(null), 900);
      // Real feedback: how good was the move anyway? (Stockfish symbol, filled in when it arrives.)
      const at = fen;
      api.get(`/annotate?fen=${encodeURIComponent(at)}&move=${m.uci}`).then((a) => setFeedback((f) => (f?.uci === m.uci
        ? { ...f, badge: a, text: a.loss_cp <= 30
          ? `${m.san} is a good move, but it is not in your repertoire. Try again.`
          : `${m.san} costs ${pawns(a.loss_cp).replace("+", "")} pawns and is not in your repertoire. Try again.` }
        : f))).catch(() => {});
    }
  }

  function showHint() {
    if (!node?.user_move) return;
    const mv = new Chess(fen).move({ from: node.user_move.slice(0, 2), to: node.user_move.slice(2, 4), promotion: node.user_move[4] });
    if (hint === 0) {
      setHint(1);
      setFeedback({ kind: "hint", text: `Hint: move your ${PIECE[mv.piece]}.` });
    } else {
      setHint(2);
      setFeedback({ kind: "hint", text: `The move is ${node.user_move_san}.` });
    }
  }

  function restart() {
    setPath([]);
    setBad(null);
    setHint(0);
    setFeedback(null);
    setScore({ right: 0, wrong: 0 });
  }

  function switchMode(m) {
    setMode(m);
    setBad(null);
    setHint(0);
    setFeedback(null);
  }

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
    setFeedback(null);
    setPath(out);
  }
  const myColor = tree.color === "white" ? "w" : "b";
  const boardArrows = practice
    ? (hint === 2 && node?.user_move ? [arrow(node.user_move, ARROW.good)] : [])
    : stored.filter((m) => m.kind !== "opp").map((m) => arrow(m.uci, m.kind === "main" ? ARROW.good : ARROW.goodSoft));
  // Hint level 1 lights up the square of the piece to move.
  const boardHighlight = bad ? bad.uci : practice && hint === 1 && node?.user_move ? node.user_move.slice(0, 2).repeat(2) : last?.uci;

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
        <Board max={600} evaluation={practice ? undefined : evaluation} fen={shownFen} orientation={orientation} explore={false}
          highlight={boardHighlight} arrows={boardArrows}
          canDrag={practice ? (p) => userTurn && !bad && p[0] === myColor : undefined}
          onMove={(m) => !m.reset && (practice ? practiceMove(m) : play(m.uci, m.san))} />
        {!practice && !lastSaved && <p className="hint">{last.san} is not in this repertoire yet{editable ? ". Press Save to add it." : "."}</p>}
        {msg && <p className="ok small">{msg}</p>}
        {error && <div className="alert">{error}</div>}
      </div>

      {/* ---------- right: engine, move list, next moves, controls ---------- */}
      <aside className="sv-tools">
        <div className="sv-mode" role="tablist" aria-label="Mode">
          <button role="tab" aria-selected={practice} className={practice ? "on" : ""} onClick={() => switchMode("practice")}>Practice</button>
          <button role="tab" aria-selected={!practice} className={!practice ? "on" : ""} onClick={() => switchMode("explore")}>Explore &amp; edit</button>
        </div>
        {practice ? (
          <div className="practice">
            <p className="practice-turn">
              {feedback?.kind === "done" ? "Line complete" : userTurn ? `Your move (${tree.color})` : "Opponent is moving…"}
            </p>
            {feedback && (
              <p className={`practice-msg ${feedback.kind}`} role="status">
                {feedback.badge && <MoveBadge a={feedback.badge} withLabel />} {feedback.text}
              </p>
            )}
            {!feedback && <p className="muted small">The opponent's moves are played for you. Play your repertoire move on the board.</p>}
            {node?.comment && userTurn && feedback?.kind !== "bad" && <p className="practice-note">{node.comment}</p>}
            <div className="practice-score">
              <span><b className="good">{score.right}</b> right</span>
              <span><b className="bad">{score.wrong}</b> mistakes</span>
            </div>
            <div className="practice-actions">
              {feedback?.kind === "done" ? (
                <button className="primary" onClick={restart}>Practise another line</button>
              ) : (
                <button onClick={showHint} disabled={!userTurn || !node?.user_move || hint === 2}>{hint === 0 ? "Hint" : "Show the move"}</button>
              )}
              <button className="ghost" onClick={restart}>Restart</button>
            </div>
          </div>
        ) : (
        <EnginePanel onInfo={setEvaluation} fen={fen} playerColor={tree.color} hideMasters compact />
        )}
        <div className="sv-moves">
          {rows.length === 0 && !practice && <p className="muted small pad">Starting position. Pick a line on the left, a move below, or play on the board.</p>}
          {rows.map(([i, w, b]) => (
            <div className="sv-row" key={i}>
              <span className="sv-num">{i / 2 + 1}</span>
              <button className={`sv-mv ${i === path.length - 1 ? "current" : ""}`} disabled={practice} onClick={() => setPath(path.slice(0, i + 1))}>{w.san}</button>
              {b ? <button className={`sv-mv ${i + 1 === path.length - 1 ? "current" : ""}`} disabled={practice} onClick={() => setPath(path.slice(0, i + 2))}>{b.san}</button> : <span />}
            </div>
          ))}
        </div>
        {!practice && <div className="sv-next">
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
        </div>}
        <div className="sv-controls">
          {!practice && <>
          <button onClick={() => setPath([])} title="First move" aria-label="First move">⏮</button>
          <button onClick={() => setPath(path.slice(0, -1))} disabled={!path.length} title="Previous move (←)" aria-label="Previous move">❮</button>
          <button id="sv-next-btn" onClick={forward} disabled={!stored.length} title="Next move (→)" aria-label="Next move">❯</button>
          </>}
          <button onClick={() => setFlipped(!flipped)} title="Flip board" aria-label="Flip board">⇅</button>
          {!practice && editable && <button className="save" onClick={saveMove} disabled={lastSaved} title="Save this move to the repertoire">Save</button>}
          {!practice && editable && last && lastSaved && (
            <button className="prune" title="Remove the last move and everything after it" aria-label="Remove the last move"
              onClick={() => { prune(last.uci, parentFen); setPath(path.slice(0, -1)); }}>✂</button>
          )}
        </div>
      </aside>
    </section>
  );
}

// Position key after playing uci from fen (used to vary the opponent's practice replies).
function keyAfter(fen, uci) {
  const g = new Chess(fen);
  g.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] });
  return fenKey(g.fen());
}
