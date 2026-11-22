import { useState } from "react";
import { api, setToken } from "../api.js";
import Brand from "../components/Brand.jsx";

// Sign up / log in. Kept short on purpose: the form is the first thing on every screen size.
export default function Auth({ onLogin }) {
  const [mode, setMode] = useState("login");
  const [form, setForm] = useState({ username: "", password: "" });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await api.post(mode === "login" ? "/auth/login" : "/auth/signup", form);
      setToken(res.token);
      onLogin(res.user);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-wrap">
      <div className="auth-hero">
        <Brand size={40} />
        <h1>Your opening second.</h1>
        <p>Find where you leave your repertoire, and fix it.</p>
      </div>
      <form className="auth-card" onSubmit={submit} aria-label={mode === "login" ? "Log in" : "Sign up"}>
        <div className="segmented" role="tablist">
          <button type="button" role="tab" aria-selected={mode === "login"} className={mode === "login" ? "on" : ""}
            onClick={() => setMode("login")}>Log in</button>
          <button type="button" role="tab" aria-selected={mode === "signup"} className={mode === "signup" ? "on" : ""}
            onClick={() => setMode("signup")}>Sign up</button>
        </div>
        <label htmlFor="auth-user">Username</label>
        <input id="auth-user" autoComplete="username" value={form.username} onChange={set("username")} required />
        <label htmlFor="auth-pass">Password</label>
        <input id="auth-pass" type="password" autoComplete={mode === "login" ? "current-password" : "new-password"}
          value={form.password} onChange={set("password")} required minLength={mode === "signup" ? 8 : undefined} />
        {error && <div className="alert" role="alert">{error}</div>}
        <button className="primary wide" disabled={busy}>{busy ? "…" : mode === "login" ? "Log in" : "Create account"}</button>
      </form>
    </main>
  );
}
