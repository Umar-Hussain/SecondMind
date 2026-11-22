import { useEffect, useState } from "react";
import { api } from "../api.js";
import SearchBox from "../components/SearchBox.jsx";

// The user's own repertoires, laid out like Lichess's study list: a side menu, a search
// bar with sort and import buttons, and a grid of entries. Each entry shows the colour
// icon, the name, a short meta line and the first lines ("chapters") of the repertoire.
const SIDE = [
  ["all", "All repertoires"],
  ["white", "White repertoires"],
  ["black", "Black repertoires"],
  ["library", "From the library"],
  ["imported", "Imported by me"],
];

function ago(iso) {
  if (!iso) return "";
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
  if (days < 1) return "today";
  if (days < 2) return "yesterday";
  if (days < 31) return `${days} days ago`;
  const months = Math.floor(days / 30);
  return months < 12 ? `${months} month${months > 1 ? "s" : ""} ago` : `${Math.floor(months / 12)} year${months >= 24 ? "s" : ""} ago`;
}

export default function Repertoires({ repertoires, reload, onOpen, goLibrary }) {
  const [showImport, setShowImport] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState(null); // null = no search active
  const [side, setSide] = useState("all");
  const [sort, setSort] = useState("recent");
  useEffect(() => {
    if (!query) { setResults(null); return; }
    api.get(`/repertoires?q=${encodeURIComponent(query)}`).then(setResults);
  }, [query, repertoires]);

  const shown = (results ?? repertoires)
    .filter((r) => side === "all" || (side === "library" ? r.copied_from_id : side === "imported" ? !r.copied_from_id : r.color === side))
    .slice()
    .sort((a, b) => (sort === "name" ? a.name.localeCompare(b.name) : (b.created_at || "").localeCompare(a.created_at || "")));

  async function remove(r) {
    if (window.confirm(`Delete "${r.name}"? This cannot be undone.`)) {
      await api.del(`/repertoires/${r.id}`);
      reload();
    }
  }

  return (
    <section className="studies fade-in">
      <aside className="side-menu">
        {SIDE.map(([id, label]) => (
          <button key={id} className={side === id ? "active" : ""} onClick={() => setSide(id)}>{label}</button>
        ))}
        <button onClick={goLibrary}>Opening library</button>
      </aside>
      <div className="studies-main">
        <div className="studies-bar">
          <SearchBox onSearch={setQuery} placeholder="Search my repertoires (name, opening, ECO or moves)" />
          <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort">
            <option value="recent">Recently added</option>
            <option value="name">Name</option>
          </select>
          <button className="green-btn" onClick={() => setShowImport(!showImport)} aria-label="Import a repertoire" title="Import a repertoire">
            {showImport ? "✕" : "＋"}
          </button>
        </div>
        {showImport && <ImportForm onSaved={async (id) => { await reload(); setShowImport(false); onOpen(id); }} />}
        {repertoires.length === 0 && !showImport && <p className="muted pad">No repertoires yet. Import one with ＋ or add one from the library.</p>}
        {results && results.length === 0 && <p className="muted pad">Nothing matches “{query}”.</p>}
        {shown.length > 0 && (
          <div className="study-grid">
            {shown.map((r) => <StudyItem key={r.id} rep={r} onOpen={() => onOpen(r.id)} onDelete={() => remove(r)} />)}
          </div>
        )}
      </div>
    </section>
  );
}

function StudyItem({ rep, onOpen, onDelete }) {
  const chapters = rep.preview?.chapters || [];
  return (
    <article className="study-item" onClick={onOpen} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && onOpen()}>
      <div className="study-top">
        <span className={`study-icon ${rep.color}`} aria-hidden="true"><i /><i /><i /><i /></span>
        <div className="study-title">
          <h3>{rep.name}</h3>
          <span className="study-meta">
            🔒 {rep.color === "white" ? "White" : "Black"} · {rep.preview?.positions ?? 0} positions · {ago(rep.created_at)}
            {rep.match && <span className="tag match">{rep.match}</span>}
          </span>
        </div>
        <button className="icon study-del" title="Delete" aria-label={`Delete ${rep.name}`}
          onClick={(e) => { e.stopPropagation(); onDelete(); }}>✕</button>
      </div>
      <div className="study-cols">
        <ul className="chapters">
          {chapters.length === 0 && <li className="muted">No moves yet</li>}
          {chapters.map((c, i) => <li key={i} title={c.moves}><span className="ring" />{c.label}</li>)}
        </ul>
        <ul className="members">
          <li>{rep.copied_from_id ? "📚 library copy" : "📥 imported"}</li>
          {rep.preview?.opening && <li title={rep.preview.main_line}>♞ {rep.preview.opening.split(":")[0]}</li>}
        </ul>
      </div>
    </article>
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
