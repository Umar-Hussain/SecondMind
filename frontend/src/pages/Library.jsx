import { useEffect, useState } from "react";
import { api } from "../api.js";
import { ImportForm, RepCard } from "./Repertoires.jsx";
import SearchBox from "../components/SearchBox.jsx";

// Shared library: repertoires published by admins. Everyone can open them read-only and
// add a copy to their own repertoires (which they can then edit). Admins can publish and delete.
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
    const copy = await api.post(`/library/${rep.id}/copy`, { name: rep.name });
    await reloadMine();
    setMsg(`"${rep.name}" was added to your repertoires.`);
    load();
    return copy;
  }

  const shown = (items || []).filter((r) => filter === "all" || r.color === filter);
  return (
    <section>
      <div className="page-head">
        <div>
          <h2>Repertoire library</h2>
          <p className="muted">Ready-made repertoires. Open one to look through it, or add it to your repertoires and make it yours.</p>
        </div>
        <div className="row">
          <div className="segmented">
            {["all", "white", "black"].map((f) => (
              <button key={f} className={filter === f ? "on" : ""} onClick={() => setFilter(f)}>{f === "all" ? "All" : f === "white" ? "White" : "Black"}</button>
            ))}
          </div>
          {isAdmin && <button className="primary" onClick={() => setPublishing(!publishing)}>{publishing ? "Close" : "＋ Publish"}</button>}
        </div>
      </div>
      <SearchBox onSearch={setQuery} />
      {isAdmin && publishing && (
        <ImportForm endpoint="/library" title="Publish to the library (admin)" withDescription
          onSaved={() => { setPublishing(false); setMsg("Published to the library."); load(); }} />
      )}
      {msg && <p className="ok">{msg}</p>}
      {items === null && <p className="muted">Loading…</p>}
      {items && shown.length === 0 && (
        <p className="muted">
          {query ? `Nothing matches “${query}”.` : isAdmin ? "The library is empty — publish the first repertoire." : "The library is empty for now."}
        </p>
      )}
      <div className="cards">
        {shown.map((r) => (
          <RepCard key={r.id} rep={r} onOpen={() => onOpen(r.id)}
            onDelete={isAdmin ? async () => {
              if (window.confirm(`Remove "${r.name}" from the library? Users' copies are kept.`)) {
                await api.del(`/repertoires/${r.id}`);
                load();
              }
            } : null}>
            {r.match && <span className="tag match">{r.match}</span>}
            {r.in_my_repertoires
              ? <span className="tag good">in my repertoires</span>
              : !isAdmin && <button className="primary" onClick={() => add(r)}>＋ Add to mine</button>}
          </RepCard>
        ))}
      </div>
    </section>
  );
}
