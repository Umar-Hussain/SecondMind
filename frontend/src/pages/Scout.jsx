import { useState } from "react";
import { api } from "../api.js";

// Page 3: scout an opponent and show the briefing (likely openings, replies from
// the repertoire, extra lines outside it with study time, risks, novelty).
export default function Scout({ user }) {
  const [opponent, setOpponent] = useState("rival_player");
  const [platform, setPlatform] = useState("lichess");
  const [b, setB] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function go() {
    setBusy(true);
    setError(null);
    try {
      setB(await api.post("/scout", { opponent, platform }));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <h2>Scout & prepare</h2>
      <div className="form">
        <label>Opponent <input value={opponent} onChange={(e) => setOpponent(e.target.value)} /></label>
        <label>Platform
          <select value={platform} onChange={(e) => setPlatform(e.target.value)}>
            <option value="lichess">Lichess</option><option value="chesscom">Chess.com</option>
          </select>
        </label>
        <button onClick={go} disabled={busy || !opponent}>{busy ? "Scouting…" : "Prepare briefing"}</button>
      </div>
      {error && <div className="error">{error}</div>}
      {b && (
        <div className="briefing">
          <h3>Briefing vs {b.opponent} <small className="muted">#{b.briefing_id}</small></h3>
          <h4>Likely openings</h4>
          <ul>{b.likely_openings.map((o, i) => <li key={i}>{o.color}: {o.line_san} — {o.games} games, they score {Math.round(o.score * 100)}%</li>)}</ul>
          <h4>Your prepared replies (from your repertoire)</h4>
          <ul>{b.recommended_replies.map((r, i) => <li key={i}><b>{r.san}</b> <span className="badge">repertoire move</span> <span className="muted">{r.repertoire}</span></li>)}</ul>
          <h4>Extra lines (outside your repertoire)</h4>
          {b.extra_lines.length === 0 && <p className="muted">No sound short line found.</p>}
          {b.extra_lines.map((x, i) => (
            <div key={i} className="card">
              <span className="tag extra">extra line · not in your repertoire</span>
              <p><code>{x.moves_san.join(" ")}</code></p>
              <p>{x.goal}</p>
              <p className="muted">Ends at {(x.final_eval_cp / 100).toFixed(2)} for you · ~{x.study_minutes} min to learn · quizzes scheduled</p>
            </div>
          ))}
          {b.novelty && (
            <>
              <h4>Surprise idea</h4>
              <p><b>{b.novelty.san}</b> — engine-sound ({b.novelty.loss_cp} cp from best) and rare at master level. Line: {b.novelty.pv_san.join(" ")}</p>
            </>
          )}
          {b.risks.length > 0 && (<><h4>Risks & targets</h4><ul>{b.risks.map((r, i) => <li key={i}>{r}</li>)}</ul></>)}
          {b.key_ideas.length > 0 && (<><h4>Read before the game</h4><ul>{b.key_ideas.map((k, i) => <li key={i}>{k}</li>)}</ul></>)}
        </div>
      )}
    </section>
  );
}
