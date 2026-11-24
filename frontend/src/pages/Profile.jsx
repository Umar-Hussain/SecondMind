import { useState } from "react";
import { api } from "../api.js";

// Profile: linked chess accounts and rating, plus fetching and analysing games.
export default function Profile({ user, setUser, analysis }) {
  const [form, setForm] = useState({
    display_name: user.display_name || "",
    lichess_username: user.lichess_username || "",
    chesscom_username: user.chesscom_username || "",
    rating: user.rating || "",
  });
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

  // Runs on the server in the background: the user can leave this page meanwhile.
  async function analyze() {
    setError(null);
    try {
      await analysis.start();
    } catch (e) {
      setError(e.message);
    }
  }
  const job = analysis.job;
  const busy = job?.state === "running";
  const summary = job?.state === "done" ? job.summary : null;

  return (
    <section className="profile-page fade-in">
      <h2>Profile</h2>
      <div className="profile-grid">
      <div className="card">
        <p className="muted small">Signed in as <b>{user.username}</b>{user.role === "admin" && <span className="tag library">admin</span>}</p>
        <div className="form stack">
          <label>Display name<input value={form.display_name} onChange={set("display_name")} /></label>
          <label>Lichess username<input value={form.lichess_username} onChange={set("lichess_username")} /></label>
          <label>Chess.com username<input value={form.chesscom_username} onChange={set("chesscom_username")} /></label>
          <label>Rating<input type="number" value={form.rating} onChange={set("rating")} /></label>
        </div>
        <p className="muted small">Only public usernames — SecondMind never asks for a chess-site password.</p>
        <button onClick={save}>Save profile</button>
        {msg && <span className="ok small"> {msg}</span>}
      </div>
      <div className="profile-side">
      <div className="card">
        <h3>Analyse my games</h3>
        <p className="muted small">Fetches your recent rated games from both sites, finds opening leaks and compares them with your repertoires.</p>
        <button className="primary" onClick={analyze} disabled={busy || !(user.lichess_username || user.chesscom_username)}>
          {busy ? `${job.message}… ${job.percent}%` : "Fetch & analyse games"}
        </button>
        {busy && <p className="muted small">This runs in the background. You can keep using the other pages.</p>}
        {job?.state === "error" && <div className="alert">{job.error}</div>}
        {summary && (
          <ul>
            <li>{summary.games_fetched} games fetched, {summary.games_new} new (duplicates across sites removed)</li>
            <li>{summary.leaks} opening leaks found</li>
            <li>{summary.repertoires_analyzed} repertoire(s): {summary.deviations} deviations, {summary.uncovered} uncovered lines</li>
            {summary.warnings.map((w) => <li key={w} className="alert">{w}</li>)}
          </ul>
        )}
      </div>
      <PasswordCard />
      </div>
      </div>
      {error && <div className="alert">{error}</div>}
    </section>
  );
}

function PasswordCard() {
  const [form, setForm] = useState({ current: "", next: "", again: "" });
  const [msg, setMsg] = useState(null);
  const [error, setError] = useState(null);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  async function submit(e) {
    e.preventDefault();
    setMsg(null);
    setError(null);
    if (form.next !== form.again) {
      setError("The new passwords do not match.");
      return;
    }
    try {
      await api.post("/auth/password", { current_password: form.current, new_password: form.next });
      setForm({ current: "", next: "", again: "" });
      setMsg("Password changed.");
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <form className="card" onSubmit={submit}>
      <h3>Change password</h3>
      <div className="form stack">
        <label>Current password<input type="password" autoComplete="current-password" value={form.current} onChange={set("current")} required /></label>
        <label>New password<input type="password" autoComplete="new-password" minLength={8} value={form.next} onChange={set("next")} required /></label>
        <label>Repeat new password<input type="password" autoComplete="new-password" minLength={8} value={form.again} onChange={set("again")} required /></label>
      </div>
      <button>Change password</button>
      {msg && <span className="ok small"> {msg}</span>}
      {error && <div className="alert">{error}</div>}
    </form>
  );
}
