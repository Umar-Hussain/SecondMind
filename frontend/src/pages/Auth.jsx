import { useState } from "react";
import { api, setToken } from "../api.js";
import Brand from "../components/Brand.jsx";

// Sign up / log in. Only a username and password are needed; chess accounts are linked later.
export default function Auth({ onLogin }) {
  const [mode, setMode] = useState("login");
  const [form, setForm] = useState({ username: "", password: "", lichess_username: "", chesscom_username: "" });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = mode === "login"
        ? { username: form.username, password: form.password }
        : { ...form, lichess_username: form.lichess_username || null, chesscom_username: form.chesscom_username || null };
      const res = await api.post(mode === "login" ? "/auth/login" : "/auth/signup", body);
      setToken(res.token);
      onLogin(res.user);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-wrap">
      <div className="auth-hero">
        <Brand size={44} />
        <h1>Your opening second.</h1>
        <p>
          SecondMind reads your Lichess and Chess.com games, shows where you leave your repertoire,
          explains the plans with cited theory, and trains you with engine-checked quizzes.
        </p>
        <ul className="hero-points">
          <li><span className="dot good" />Every move checked by Stockfish</li>
          <li><span className="dot primary" />Ready-made repertoires in the library</li>
          <li><span className="dot warn" />Gambits respected, never called blunders</li>
        </ul>
      </div>
      <form className="auth-card" onSubmit={submit}>
        <div className="segmented">
          <button type="button" className={mode === "login" ? "on" : ""} onClick={() => setMode("login")}>Log in</button>
          <button type="button" className={mode === "signup" ? "on" : ""} onClick={() => setMode("signup")}>Sign up</button>
        </div>
        <label>Username<input autoComplete="username" value={form.username} onChange={set("username")} required /></label>
        <label>Password
          <input type="password" autoComplete={mode === "login" ? "current-password" : "new-password"}
            value={form.password} onChange={set("password")} required minLength={mode === "signup" ? 8 : undefined} />
        </label>
        {mode === "signup" && (
          <>
            <label>Lichess username <small>(optional)</small><input value={form.lichess_username} onChange={set("lichess_username")} /></label>
            <label>Chess.com username <small>(optional)</small><input value={form.chesscom_username} onChange={set("chesscom_username")} /></label>
            <p className="muted small">No chess-site password is ever needed — only public usernames.</p>
          </>
        )}
        {error && <div className="alert">{error}</div>}
        <button className="primary wide" disabled={busy}>{busy ? "…" : mode === "login" ? "Log in" : "Create account"}</button>
      </form>
    </div>
  );
}
