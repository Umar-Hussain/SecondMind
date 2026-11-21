import { useState } from "react";
import { api } from "../api.js";

// Page 1: link a Lichess and/or Chess.com username (no password ever), then run the analysis.
export default function Connect({ user, setUser }) {
  const [lichess, setLichess] = useState("demo_player");
  const [chesscom, setChesscom] = useState("demo_player_cc");
  const [rating, setRating] = useState(1600);
  const [busy, setBusy] = useState(false);
  const [summary, setSummary] = useState(null);
  const [error, setError] = useState(null);

  async function connect() {
    setError(null);
    try {
      const u = await api.post("/users", {
        lichess_username: lichess || null,
        chesscom_username: chesscom || null,
        rating: Number(rating) || null,
      });
      setUser(u);
    } catch (e) {
      setError(e.message);
    }
  }

  async function analyze() {
    setBusy(true);
    setError(null);
    try {
      setSummary(await api.post("/analyze", { user_id: user.id, max_games: 200 }));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <h2>Connect your accounts</h2>
      <p className="muted">Only public usernames are needed. RepertoireAI never asks for a password.</p>
      <div className="form">
        <label>Lichess username <input value={lichess} onChange={(e) => setLichess(e.target.value)} /></label>
        <label>Chess.com username <input value={chesscom} onChange={(e) => setChesscom(e.target.value)} /></label>
        <label>Your rating <input type="number" value={rating} onChange={(e) => setRating(e.target.value)} /></label>
        <button onClick={connect} disabled={!lichess && !chesscom}>{user ? "Re-link" : "Connect"}</button>
      </div>
      {user && (
        <div className="card">
          <p>
            Connected as user #{user.id} ({user.lichess_username || "–"} / {user.chesscom_username || "–"}).
          </p>
          <button onClick={analyze} disabled={busy}>{busy ? "Analysing games with Stockfish…" : "Fetch & analyse games"}</button>
          {summary && (
            <ul>
              <li>{summary.games_fetched} games fetched, {summary.games_new} new (duplicates across platforms removed)</li>
              <li>{summary.leaks} opening leaks found</li>
              <li>{summary.repertoires_analyzed} repertoire(s): {summary.deviations} deviations, {summary.uncovered} uncovered lines</li>
              {summary.warnings.map((w) => <li key={w} className="error">{w}</li>)}
            </ul>
          )}
        </div>
      )}
      {error && <div className="error">{error}</div>}
    </section>
  );
}
