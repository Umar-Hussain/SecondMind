import { useEffect, useState } from "react";
import { api, setToken } from "../api.js";
import Brand from "../components/Brand.jsx";

// Sign up / sign in as a split screen: a blue panel with rotating feature slides on the
// left, the form card on the right. On phones the slides are hidden so the form comes first.
const SLIDES = [
  { title: "Find your leaks", text: "See the exact positions where you leave your repertoire, and what they cost you." },
  { title: "Prepare", text: "Scout your next opponent and walk into the game knowing their favourite lines." },
  { title: "Train", text: "Short quizzes from your own games, repeated just before you would forget." },
  { title: "Trust the answers", text: "Every move is checked by Stockfish. The AI only quotes what our tools verified." },
];

export default function Auth({ initialMode = "login", onLogin, onBack }) {
  const [mode, setMode] = useState(initialMode);
  const [form, setForm] = useState({ username: "", password: "", lichess_username: "" });
  const [show, setShow] = useState(false);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [slide, setSlide] = useState(0);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const signup = mode === "signup";

  useEffect(() => {
    const t = setInterval(() => setSlide((s) => (s + 1) % SLIDES.length), 5000);
    return () => clearInterval(t);
  }, []);
  useEffect(() => setError(null), [mode]);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = signup
        ? { username: form.username, password: form.password, ...(form.lichess_username.trim() ? { lichess_username: form.lichess_username.trim() } : {}) }
        : { username: form.username, password: form.password };
      const res = await api.post(signup ? "/auth/signup" : "/auth/login", body);
      setToken(res.token);
      onLogin(res.user);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const s = SLIDES[slide];
  return (
    <div className="auth-split">
      <aside className="auth-panel">
        <button className="auth-brand" onClick={onBack} aria-label="Back to the home page"><Brand size={36} /></button>
        <p className="auth-panel-tag">Your personal opening second</p>
        <div className="auth-slide" key={slide}>
          <h2>{s.title}</h2>
          <p>{s.text}</p>
        </div>
        <div className="auth-dots" role="tablist" aria-label="Features">
          {SLIDES.map((x, i) => (
            <button key={x.title} role="tab" aria-selected={i === slide} aria-label={x.title}
              className={i === slide ? "on" : ""} onClick={() => setSlide(i)} />
          ))}
        </div>
        <ul className="auth-facts">
          <li><b>Stockfish</b><span>Every move checked</span></li>
          <li><b>Lichess + Chess.com</b><span>Your games, no password</span></li>
          <li><b>Free</b><span>For every player</span></li>
        </ul>
      </aside>

      <main className="auth-side">
        <button className="link auth-back" onClick={onBack}>← Home</button>
        <form className="auth-form" onSubmit={submit} aria-label={signup ? "Create an account" : "Sign in"}>
          <h1>{signup ? "Get started" : "Welcome back"}</h1>
          <p className="muted">{signup ? "Create a free account to save your repertoires and progress." : "Sign in to continue your preparation."}</p>

          <label htmlFor="auth-user">Username</label>
          <input id="auth-user" autoComplete="username" placeholder="your_username" value={form.username}
            onChange={set("username")} required autoFocus />
          {signup && <span className="help">3 to 32 letters, numbers, _ or -.</span>}

          <label htmlFor="auth-pass">Password</label>
          <div className="pw-wrap">
            <input id="auth-pass" type={show ? "text" : "password"} autoComplete={signup ? "new-password" : "current-password"}
              placeholder="••••••••" value={form.password} onChange={set("password")} required minLength={signup ? 8 : undefined} />
            <button type="button" className="pw-eye" onClick={() => setShow(!show)} aria-label={show ? "Hide password" : "Show password"}>
              {show ? "Hide" : "Show"}
            </button>
          </div>
          {signup && <span className="help">At least 8 characters.</span>}

          {signup && (
            <>
              <label htmlFor="auth-lichess">Lichess username <span className="muted">(optional)</span></label>
              <input id="auth-lichess" placeholder="So we can fetch your games" value={form.lichess_username} onChange={set("lichess_username")} />
            </>
          )}

          {error && <div className="alert" role="alert">{error}</div>}
          <button className="primary wide big" disabled={busy}>{busy ? "Please wait…" : signup ? "Create account" : "Sign in"}</button>
          <p className="auth-switch">
            {signup ? "Already have an account? " : "New to SecondMind? "}
            <button type="button" className="link" onClick={() => setMode(signup ? "login" : "signup")}>{signup ? "Sign in" : "Create an account"}</button>
          </p>
        </form>
      </main>
    </div>
  );
}
