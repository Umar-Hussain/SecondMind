import { useEffect, useState } from "react";
import { api } from "../api.js";
import { ImportForm } from "./Repertoires.jsx";
import PageHero from "../components/PageHero.jsx";
import SearchBox from "../components/SearchBox.jsx";
import MiniBoard from "../components/MiniBoard.jsx";

// Shared library, laid out like Lichess's "Chess openings" page: a grid of cards, each
// with the repertoire's name, its key move, a mini board of the opening position and a
// side strip for the colour. Everyone can open a card read-only and add a copy to their
// own repertoires; admins can publish and delete.
export default function Library({ user, onOpen, reloadMine }) {
  const [items, setItems] = useState(null);
  const [filter, setFilter] = useState("all");
  const [publishing, setPublishing] = useState(false);
  const [msg, setMsg] = useState(null);
  const [query, setQuery] = useState("");
  const isAdmin = user.role === "admin";

  const load = (q = query) => api.get(`/library${q ? `?q=${encodeURIComponent(q)}` : ""}`).then(setItems);
  useEffect(() => { load(query); }, [query]); // eslint-disable-line react-hooks/exhaustive-deps

  async function add(rep) {
    await api.post(`/library/${rep.id}/copy`, { name: rep.name });
    await reloadMine();
    setMsg(`"${rep.name}" was added to your repertoires.`);
    load();
  }

  async function remove(rep) {
    if (window.confirm(`Remove "${rep.name}" from the library? Users' copies are kept.`)) {
      await api.del(`/repertoires/${rep.id}`);
      load();
    }
  }

  const shown = (items || []).filter((r) => filter === "all" || r.color === filter);
  return (
    <section className="fade-in">
      <div className="lib-top">
        <SearchBox onSearch={setQuery} placeholder="Search by name, opening, ECO code or moves (1.e4 c6)" />
        <div className="segmented">
          {["all", "white", "black"].map((f) => (
            <button key={f} className={filter === f ? "on" : ""} onClick={() => setFilter(f)}>{f === "all" ? "All" : f === "white" ? "White" : "Black"}</button>
          ))}
        </div>
      </div>
      <div className="page-head">
        <h1 className="page-title">Opening library</h1>
        {isAdmin && <button className="primary" onClick={() => setPublishing(!publishing)}>{publishing ? "Close" : "＋ Publish"}</button>}
      </div>
      {isAdmin && publishing && (
        <ImportForm endpoint="/library" title="Publish to the library" withDescription
          onSaved={() => { setPublishing(false); setMsg("Published to the library."); load(); }} />
      )}
      {msg && <p className="ok">{msg}</p>}
      {items === null && <p className="muted">Loading…</p>}
      {items && shown.length === 0 && (query || filter !== "all"
        ? <p className="muted">Nothing matches{query ? ` “${query}”` : ""}.</p>
        : (
          <PageHero title={isAdmin ? "Start the library" : "The library is being stocked"}
            fen="rnbqkb1r/pp2pppp/3p1n2/8/3NP3/8/PPP2PPP/RNBQKB1R w KQkq - 1 5"
            text={isAdmin
              ? "Publish ready-made repertoires here. Every player can copy one into their own list, practise it and track it against their games."
              : "Ready-made repertoires will appear here, to copy and practise. Meanwhile, import your own from a PGN file or a Lichess study on the Repertoires page."}
            steps={[["Pick an opening", "Search by name, ECO code or moves like 1.e4 c6."],
              ["Copy it", "One click adds it to your repertoires."],
              ["Practise it", "The app plays the opponent's moves; you answer."]]}>
            {isAdmin && <button className="primary big" onClick={() => setPublishing(true)}>＋ Publish a repertoire</button>}
          </PageHero>
        ))}
      <div className="opening-grid">
        {shown.map((r) => (
          <article key={r.id} className="opening-card" onClick={() => onOpen(r.id)} tabIndex={0}
            onKeyDown={(e) => e.key === "Enter" && onOpen(r.id)} aria-label={`Open ${r.name}`}>
            <span className={`oc-pill ${r.color}`}>{r.color === "white" ? "White" : "Black"}</span>
            <header className="oc-head">
              <span className="oc-name" title={r.name}>{r.name}</span>
              <span className="oc-move">{r.preview?.key_move}</span>
            </header>
            <div className="oc-body">
              <div className={`oc-strip ${r.color}`} title={`${r.color === "white" ? "White" : "Black"} repertoire · ${r.preview?.positions ?? 0} positions`} />
              <MiniBoard fen={r.preview?.fen || "start"} orientation={r.color} width={236} />
            </div>
            <footer className="oc-foot" onClick={(e) => e.stopPropagation()}>
              <span className="muted small oc-line" title={r.preview?.main_line}>{r.match || r.preview?.opening || r.description}</span>
              {r.in_my_repertoires
                ? <span className="tag good">added</span>
                : !isAdmin && <button className="mini primary" onClick={() => add(r)}>＋ Add</button>}
              {isAdmin && <button className="mini ghost danger-text" onClick={() => remove(r)} aria-label={`Delete ${r.name}`}>✕</button>}
            </footer>
          </article>
        ))}
      </div>
    </section>
  );
}
