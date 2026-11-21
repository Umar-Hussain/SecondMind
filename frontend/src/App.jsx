import { useCallback, useEffect, useState } from "react";
import { api, getToken, setToken } from "./api.js";
import Brand from "./components/Brand.jsx";
import Auth from "./pages/Auth.jsx";
import Repertoires from "./pages/Repertoires.jsx";
import Library from "./pages/Library.jsx";
import Workspace from "./pages/Workspace.jsx";
import Deviations from "./pages/Deviations.jsx";
import Report from "./pages/Report.jsx";
import Scout from "./pages/Scout.jsx";
import Train from "./pages/Train.jsx";
import Progress from "./pages/Progress.jsx";
import Profile from "./pages/Profile.jsx";
import Users from "./pages/Users.jsx";

const PAGES = [
  ["repertoires", "Repertoires"],
  ["library", "Library"],
  ["deviations", "Deviations"],
  ["report", "Gap report"],
  ["scout", "Prepare"],
  ["train", "Train"],
  ["progress", "Progress"],
];

export default function App() {
  const [user, setUser] = useState(null);
  const [checking, setChecking] = useState(Boolean(getToken()));
  const [page, setPage] = useState("repertoires");
  const [openRep, setOpenRep] = useState(null); // repertoire id shown in the workspace
  const [repertoires, setRepertoires] = useState([]);
  const [status, setStatus] = useState(null);
  const [menu, setMenu] = useState(false);

  // Restore the session from the stored token.
  useEffect(() => {
    if (!getToken()) return;
    api.get("/auth/me").then(setUser).catch(() => setToken(null)).finally(() => setChecking(false));
  }, []);
  useEffect(() => {
    const onLogout = () => { setUser(null); setOpenRep(null); };
    window.addEventListener("secondmind:logout", onLogout);
    return () => window.removeEventListener("secondmind:logout", onLogout);
  }, []);
  useEffect(() => { api.get("/engine/status").then(setStatus).catch(() => setStatus({ down: true })); }, []);

  const reloadReps = useCallback(async () => {
    if (user) setRepertoires(await api.get("/repertoires"));
  }, [user]);
  useEffect(() => { reloadReps().catch(() => {}); }, [reloadReps]);

  function logout() {
    setToken(null);
    setUser(null);
    setOpenRep(null);
    setMenu(false);
  }

  function toggleTheme() {
    const light = document.documentElement.dataset.theme !== "light";
    if (light) document.documentElement.dataset.theme = "light";
    else delete document.documentElement.dataset.theme;
    try { localStorage.setItem("secondmind.theme", light ? "light" : "dark"); } catch { /* ignore */ }
  }

  function go(id) {
    setPage(id);
    setOpenRep(null);
    setMenu(false);
  }

  if (checking) return <div className="center muted">Loading…</div>;
  if (!user) return <Auth onLogin={(u) => { setUser(u); setPage("repertoires"); }} />;

  return (
    <div className="app">
      <header className="topbar">
        <button className="brand-btn" onClick={() => go("repertoires")}><Brand /></button>
        <nav className={menu ? "open" : ""}>
          {[...PAGES, ...(user.role === "admin" ? [["users", "Users"]] : [])].map(([id, label]) => (
            <button key={id} className={page === id && !openRep ? "active" : ""} onClick={() => go(id)}>{label}</button>
          ))}
        </nav>
        <div className="topbar-right">
          {status && !status.down && (
            <span className="status-dots" title={`Stockfish ${status.stockfish ? "ready" : "missing"} · AI ${status.llm ? status.provider : "off (templates)"}`}>
              <span className={`dot ${status.stockfish ? "good" : "bad"}`} /> engine
              <span className={`dot ${status.llm ? "good" : "muted"}`} /> AI
            </span>
          )}
          <button className={`user-btn ${page === "profile" ? "active" : ""}`} onClick={() => go("profile")}>
            {user.display_name || user.username}
            {user.role === "admin" && <span className="tag library">admin</span>}
          </button>
          <button className="ghost" title="Light / dark theme" onClick={toggleTheme}>◐</button>
          <button className="ghost" onClick={logout}>Log out</button>
          <button className="hamburger" onClick={() => setMenu(!menu)} aria-label="Menu">☰</button>
        </div>
      </header>
      <main>
        {openRep ? (
          <Workspace repId={openRep} user={user} onBack={() => { setOpenRep(null); reloadReps(); }}
            onOpen={(id) => { reloadReps(); setOpenRep(id); }} />
        ) : (
          <>
            {page === "repertoires" && <Repertoires repertoires={repertoires} reload={reloadReps} onOpen={setOpenRep} goLibrary={() => go("library")} />}
            {page === "library" && <Library user={user} onOpen={setOpenRep} reloadMine={reloadReps} />}
            {page === "deviations" && <Deviations repertoires={repertoires} />}
            {page === "report" && <Report user={user} />}
            {page === "scout" && <Scout user={user} />}
            {page === "train" && <Train user={user} />}
            {page === "progress" && <Progress user={user} />}
            {page === "profile" && <Profile user={user} setUser={setUser} />}
            {page === "users" && user.role === "admin" && <Users />}
          </>
        )}
      </main>
      <footer className="foot muted small">SecondMind · every move checked by Stockfish · AI explanations verified before you see them</footer>
    </div>
  );
}
