import { useState } from "react";
import { api } from "../api.js";

// Profile: linked chess accounts and rating, plus fetching and analysing games.
export default function Profile({ user, setUser }) {
  const [form, setForm] = useState({
    display_name: user.display_name || "",
    lichess_username: user.lichess_username || "",
    chesscom_username: user.chesscom_username || "",
    rating: user.rating || "",
  });
  const [busy, setBusy] = useState(false);
  const [summary, setSummary] = useState(null);
  const [msg, setMsg] = useState(null);
  const [error, setError] = useState(null);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  async function save() {
    setError(null);
    try {
      const u = await api.patch("/auth/me", { ...form, rating: form.rating ? Number(form.rating) : null });
      setUser({ ...user, ...u });
      setMsg("Profile saved.");
    } catch (e) {
      setError(e.message);
    }
  }

  async function analyze() {
    setBusy(true);
    setError(null);
    try {
      setSummary(await api.post("/analyze", { max_games: 200 }));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="narrow">
      <h2>Profile</h2>
      <div className="card">
        <p className="muted small">Signed in as <b>{user.username}</b>{user.role === "admin" && <span className="tag library">admin</span>}</p>
        <div className="form stack">
          <label>Display name<input value={form.display_name} onChange={set("display_name")} /></label>
          <label>Lichess username<input value={form.lichess_username} onChange={set("lichess_username")} /></label>
          <label>Chess.com username<input value={form.chesscom_username} onChange={set("chesscom_username")} /></label>
          <label>Rating<input type="number" value={form.rating} onChange={set("rating")} /></label>
        </div>
        <p className="muted small">Only public usernames — SecondMind never asks for a chess-site password.</p>
        <button className="primary" onClick={save}>Save profile</button>
        {msg && <span className="ok small"> {msg}</span>}
      </div>
      <div className="card">
        <h3>Analyse my games</h3>
        <p className="muted small">Fetches your recent rated games from both sites, finds opening leaks and compares them with your repertoires.</p>
        <button className="primary" onClick={analyze} disabled={busy || !(user.lichess_username || user.chesscom_username)}>
          {busy ? "Analysing with Stockfish…" : "Fetch & analyse games"}
        </button>
        {summary && (
          <ul>
            <li>{summary.games_fetched} games fetched, {summary.games_new} new (duplicates across sites removed)</li>
            <li>{summary.leaks} opening leaks found</li>
            <li>{summary.repertoires_analyzed} repertoire(s): {summary.deviations} deviations, {summary.uncovered} uncovered lines</li>
            {summary.warnings.map((w) => <li key={w} className="alert">{w}</li>)}
          </ul>
        )}
      </div>
      {error && <div className="alert">{error}</div>}
    </section>
  );
}
