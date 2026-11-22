import { useEffect, useState } from "react";
import { api } from "../api.js";
import SearchBox from "../components/SearchBox.jsx";

// The user's own repertoires plus an import form (PGN with variations, move list, Lichess study).
export default function Repertoires({ repertoires, reload, onOpen, goLibrary }) {
  const [showImport, setShowImport] = useState(repertoires.length === 0);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState(null); // null = no search active
  useEffect(() => {
    if (!query) { setResults(null); return; }
    api.get(`/repertoires?q=${encodeURIComponent(query)}`).then(setResults);
  }, [query, repertoires]);
  const shown = results ?? repertoires;
  return (
    <section>
      <div className="page-head">
        <div>
          <h2>My repertoires</h2>
          <p className="muted">Open one to explore and edit it on the board.</p>
        </div>
        <div className="row">
          <button className="ghost" onClick={goLibrary}>Browse the library</button>
          <button className="primary" onClick={() => setShowImport(!showImport)}>{showImport ? "Close" : "＋ Import"}</button>
        </div>
      </div>
      {repertoires.length > 0 && <SearchBox onSearch={setQuery} />}
      {showImport && <ImportForm onSaved={async (id) => { await reload(); setShowImport(false); onOpen(id); }} />}
      {repertoires.length === 0 && !showImport && <p className="muted">No repertoires yet — import one or add one from the library.</p>}
      {results && results.length === 0 && <p className="muted">Nothing matches “{query}”.</p>}
      <div className="cards">
        {shown.map((r) => (
          <RepCard key={r.id} rep={r} onOpen={() => onOpen(r.id)}
            onDelete={async () => {
              if (window.confirm(`Delete "${r.name}"? This cannot be undone.`)) {
                await api.del(`/repertoires/${r.id}`);
                reload();
              }
            }}>
            {r.match && <span className="tag match">{r.match}</span>}
          </RepCard>
        ))}
      </div>
    </section>
  );
}

export function RepCard({ rep, onOpen, onDelete, children }) {
  return (
    <div className="card rep-card">
      <div className={`rep-color ${rep.color}`}>{rep.color === "white" ? "♔" : "♚"}</div>
      <div className="rep-body">
        <h3>{rep.name}</h3>
        <p className="muted small">
          {rep.color === "white" ? "White" : "Black"}
          {rep.owner ? ` · by ${rep.owner}` : ""}
          {rep.copied_from_id ? " · from the library" : ""}
          {rep.intentional_gambit ? " · gambit" : ""}
        </p>
        {rep.description && <p className="small">{rep.description}</p>}
        <div className="row">
          <button onClick={onOpen}>Open</button>
          {children}
          {onDelete && <button className="ghost danger-text" onClick={onDelete}>Delete</button>}
        </div>
      </div>
    </div>
  );
}

export function ImportForm({ onSaved, endpoint = "/repertoires", title = "Import a repertoire", withDescription = false }) {
  const [name, setName] = useState("");
  const [color, setColor] = useState("auto");
  const [text, setText] = useState("");
  const [description, setDescription] = useState("");
  const [gambit, setGambit] = useState(false);
  const [issues, setIssues] = useState([]);
  const [error, setError] = useState(null);

  async function submit() {
    setError(null);
    const body = { name, color, intentional_gambit: gambit, description };
    const t = text.trim();
    if (t.includes("lichess.org/study/")) body.study_url = t;
    else if (t.startsWith("[") || t.includes("{") || t.includes("(")) body.pgn = t;
    else body.moves_text = t;
    try {
      const res = await api.post(endpoint, body);
      setIssues(res.issues);
      if (res.saved) onSaved(res.id);
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <div className="card import">
      <h3>{title}</h3>
      <div className="form">
        <label>Name<input value={name} onChange={(e) => setName(e.target.value)} placeholder="Optional: taken from the file" /></label>
        <label>Color
          <select value={color} onChange={(e) => setColor(e.target.value)}>
            <option value="auto">Auto (from file)</option>
            <option value="white">White</option>
            <option value="black">Black</option>
          </select>
        </label>
        <label className="check"><input type="checkbox" checked={gambit} onChange={(e) => setGambit(e.target.checked)} /> Gambit repertoire</label>
        <label>PGN file<input type="file" accept=".pgn,.txt" onChange={async (e) => e.target.files[0] && setText(await e.target.files[0].text())} /></label>
      </div>
      {withDescription && <input className="full" placeholder="Short description shown in the library" value={description} onChange={(e) => setDescription(e.target.value)} />}
      <textarea rows={6} placeholder="Paste a PGN with variations, a move list (1.e4 c6 2.d4 d5 3.e5) or a Lichess study link"
        value={text} onChange={(e) => setText(e.target.value)} />
      <button className="primary" onClick={submit} disabled={!text.trim()}>Import</button>
      {error && <div className="alert">{error}</div>}
      {issues.length > 0 && (
        <ul className="issues">{issues.map((i, k) => <li key={k} className={i.level}>{i.level}: {i.location} — {i.message}</li>)}</ul>
      )}
    </div>
  );
}
