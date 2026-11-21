import { useEffect, useState } from "react";
import { api } from "../api.js";
import Board, { arrow } from "../components/Board.jsx";
import EnginePanel from "../components/EnginePanel.jsx";

const BADGE = { repertoire: "repertoire move", master: "master choice", engine: "engine choice" };

// Page 1c: ranked deviations from the user's own repertoire (most games first),
// detail view with board, played vs repertoire vs recommended, games, explanation
// with citations, and live Stockfish analysis. Second tab: uncovered opponent lines.
export default function Deviations({ repertoires }) {
  const [repId, setRepId] = useState(repertoires[0]?.id);
  const [tab, setTab] = useState("deviations");
  const [sort, setSort] = useState("games");
  const [list, setList] = useState([]);
  const [uncovered, setUncovered] = useState([]);
  const [detail, setDetail] = useState(null);
  const [exploreFen, setExploreFen] = useState(null);

  useEffect(() => { if (!repId && repertoires[0]) setRepId(repertoires[0].id); }, [repertoires]);
  useEffect(() => {
    if (!repId) return;
    api.get(`/deviations?repertoire_id=${repId}&sort=${sort}`).then(setList);
    api.get(`/uncovered?repertoire_id=${repId}`).then(setUncovered);
    setDetail(null);
  }, [repId, sort]);

  async function open(d) {
    setDetail({ loading: true });
    const full = await api.get(`/deviations/${d.id}`);
    setDetail(full);
    setExploreFen(full.fen);
  }

  if (!repertoires.length) return <p>Import a repertoire first, then run the analysis on the Connect page.</p>;

  return (
    <section>
      <h2>Where you leave your repertoire</h2>
      <div className="toolbar">
        <select value={repId} onChange={(e) => setRepId(Number(e.target.value))}>
          {repertoires.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
        </select>
        <button className={tab === "deviations" ? "active" : ""} onClick={() => setTab("deviations")}>Your deviations</button>
        <button className={tab === "uncovered" ? "active" : ""} onClick={() => setTab("uncovered")}>Uncovered opponent lines</button>
        {tab === "deviations" && (
          <select value={sort} onChange={(e) => setSort(e.target.value)}>
            <option value="games">Most games first</option>
            <option value="impact">Games × average loss</option>
          </select>
        )}
      </div>

      {tab === "deviations" ? (
        <div className="grid2">
          <table className="list">
            <thead><tr><th>#</th><th>You played</th><th>Repertoire</th><th>Games</th><th>W/D/L</th><th>Loss</th><th>Verdict</th></tr></thead>
            <tbody>
              {list.map((d, i) => (
                <tr key={d.id} onClick={() => open(d)} className={detail?.id === d.id ? "selected" : ""}>
                  <td>{i + 1}</td><td><b>{d.played_san}</b></td><td>{d.repertoire_san}</td><td>{d.games_count}</td>
                  <td>{d.results.win}/{d.results.draw}/{d.results.loss}</td>
                  <td>{(d.avg_eval_loss / 100).toFixed(2)}</td>
                  <td><span className={`tag ${d.classification}`}>{d.classification}</span>{d.is_gambit && <span className="tag gambit">gambit</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div>
            {detail?.loading && <p>Loading…</p>}
            {detail && !detail.loading && (
              <div className="detail">
                <Board
                  fen={detail.fen}
                  orientation={detail.color}
                  arrows={[arrow(detail.played_move, "rgb(220,60,60)"), arrow(detail.recommended_move, "rgb(40,160,80)")].filter(Boolean)}
                  onMove={(m) => setExploreFen(m.fen)}
                />
                <p>
                  You played <b className="bad">{detail.played_san}</b> ({detail.games_count} games) · repertoire:{" "}
                  <b>{detail.repertoire_san}</b> · recommended: <b className="good">{detail.recommended_san}</b>{" "}
                  <span className="badge">{BADGE[detail.recommended_source]}</span>
                </p>
                <p className="muted">{detail.reason}</p>
                <p>{detail.explanation}</p>
                <p><i>{detail.plan}</i></p>
                <p className="muted">
                  Explanation: {detail.generated_by === "llm" ? "AI-written, moves and sources verified by the guard" : "deterministic template"}
                </p>
                {detail.citations.length > 0 && (
                  <ul className="cites">{detail.citations.map((c) => <li key={c.id}>[{c.id}] {c.title} — {c.source}</li>)}</ul>
                )}
                <p>Games: {detail.game_links.map((g, i) => <a key={g} href={g} target="_blank" rel="noreferrer">#{i + 1} </a>)}</p>
                <EnginePanel fen={exploreFen || detail.fen} playerColor={detail.color} />
              </div>
            )}
          </div>
        </div>
      ) : (
        <table className="list">
          <thead><tr><th>Opponent played</th><th>Games</th><th>Suggested reply</th></tr></thead>
          <tbody>
            {uncovered.map((u) => (
              <tr key={u.id}><td><b>{u.opponent_san}</b></td><td>{u.games_count}</td><td>{u.suggested_san || "–"}</td></tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
