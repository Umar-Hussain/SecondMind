import { useEffect, useMemo, useState } from "react";
import { Chess } from "chess.js";
import { api } from "../api.js";
import Board from "../components/Board.jsx";

const START_KEY = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -";

// Normalized position key, matching backend fen_key (first four FEN fields).
function keyOf(fen) {
  return fen.split(" ").slice(0, 4).join(" ");
}

// Page 1b: upload (PGN / move list / Lichess study), browse the tree on a board, see import errors.
export default function Repertoire({ user, repertoires, reload }) {
  const [name, setName] = useState("e4 as White");
  const [color, setColor] = useState("white");
  const [pgn, setPgn] = useState("");
  const [issues, setIssues] = useState([]);
  const [selected, setSelected] = useState(null);
  const [tree, setTree] = useState(null);
  const [path, setPath] = useState([]); // SAN moves from the start

  useEffect(() => {
    if (selected) api.get(`/repertoires/${selected}/tree`).then(setTree);
  }, [selected]);

  const nodes = useMemo(() => {
    const m = {};
    (tree?.nodes || []).forEach((n) => (m[n.fen_key] = n));
    return m;
  }, [tree]);

  const game = useMemo(() => {
    const g = new Chess();
    path.forEach((san) => g.move(san));
    return g;
  }, [path]);
  const node = nodes[keyOf(game.fen())];

  async function upload() {
    const body = { user_id: user.id, name, color };
    const text = pgn.trim();
    if (text.includes("lichess.org/study/")) body.study_url = text;
    else if (text.startsWith("[") || text.includes("{") || text.includes("(")) body.pgn = text;
    else body.moves_text = text;
    const res = await api.post("/repertoires", body);
    setIssues(res.issues);
    if (res.saved) {
      await reload();
      setSelected(res.id);
    }
  }

  async function onFile(e) {
    const f = e.target.files[0];
    if (f) setPgn(await f.text());
  }

  const choices = node
    ? [
        ...(node.user_move_san ? [{ san: node.user_move_san, kind: "yours" }] : []),
        ...node.alternatives.map((a) => ({ san: a.san, kind: "alt" })),
        ...node.opponent_moves.map((a) => ({ san: a.san, kind: "opp" })),
      ]
    : [];

  return (
    <section>
      <h2>Your repertoire</h2>
      <div className="grid2">
        <div>
          <div className="form">
            <label>Name <input value={name} onChange={(e) => setName(e.target.value)} /></label>
            <label>Color
              <select value={color} onChange={(e) => setColor(e.target.value)}>
                <option value="white">White</option>
                <option value="black">Black</option>
              </select>
            </label>
            <label>PGN file <input type="file" accept=".pgn,.txt" onChange={onFile} /></label>
          </div>
          <textarea rows={8} placeholder="Paste a PGN with variations, a move list (1.e4 c6 2.d4 d5 3.e5) or a Lichess study link"
            value={pgn} onChange={(e) => setPgn(e.target.value)} />
          <button onClick={upload} disabled={!pgn.trim()}>Import</button>
          {issues.length > 0 && (
            <ul className="issues">
              {issues.map((i, k) => (
                <li key={k} className={i.level}>{i.level}: {i.location} — {i.message}</li>
              ))}
            </ul>
          )}
          <h3>Saved repertoires</h3>
          <ul>
            {repertoires.map((r) => (
              <li key={r.id}>
                <button className="link" onClick={() => { setSelected(r.id); setPath([]); }}>
                  {r.name} ({r.color}){r.intentional_gambit ? " · gambit" : ""}
                </button>
              </li>
            ))}
          </ul>
        </div>
        {tree && (
          <div>
            <Board fen={game.fen()} orientation={tree.color} explore={false} width={380} />
            <p className="muted">
              {path.length ? path.join(" ") : "Start position"}{" "}
              {path.length > 0 && <button className="link" onClick={() => setPath(path.slice(0, -1))}>← back</button>}
            </p>
            {node?.comment && <p className="comment">{node.comment}</p>}
            <div>
              {choices.length === 0 && <span className="muted">End of prepared line.</span>}
              {choices.map((c) => (
                <button key={c.san + c.kind} className={`chip ${c.kind}`} onClick={() => setPath([...path, c.san])}>
                  {c.san}{c.kind === "yours" ? " ★" : c.kind === "alt" ? " (alt)" : ""}
                </button>
              ))}
            </div>
            <p className="muted">{tree.nodes.length} positions · transpositions share one node</p>
          </div>
        )}
      </div>
    </section>
  );
}

export { START_KEY };
