import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import Connect from "./pages/Connect.jsx";
import Repertoire from "./pages/Repertoire.jsx";
import Deviations from "./pages/Deviations.jsx";
import Report from "./pages/Report.jsx";
import Scout from "./pages/Scout.jsx";
import Train from "./pages/Train.jsx";
import Progress from "./pages/Progress.jsx";

const PAGES = [
  ["connect", "Connect"],
  ["repertoire", "Repertoire"],
  ["deviations", "Deviations"],
  ["report", "Gap report"],
  ["scout", "Scout & prepare"],
  ["train", "Train"],
  ["progress", "Progress"],
];

// The current user id is remembered in localStorage (a per-browser convenience only).
function savedUser() {
  try {
    return JSON.parse(localStorage.getItem("repai.user") || "null");
  } catch {
    return null;
  }
}

export default function App() {
  const [page, setPage] = useState("connect");
  const [user, setUserState] = useState(savedUser);
  const [repertoires, setRepertoires] = useState([]);
  const [status, setStatus] = useState(null);

  const setUser = (u) => {
    setUserState(u);
    try { localStorage.setItem("repai.user", JSON.stringify(u)); } catch { /* storage disabled */ }
  };

  const reloadReps = useCallback(async () => {
    if (user) setRepertoires(await api.get(`/repertoires?user_id=${user.id}`));
  }, [user]);

  useEffect(() => { reloadReps().catch(() => setUser(null)); }, [reloadReps]);
  useEffect(() => { api.get("/engine/status").then(setStatus).catch(() => setStatus({ down: true })); }, []);

  const needsUser = page !== "connect" && !user;
  return (
    <div className="app">
      <header>
        <h1>♞ RepertoireAI</h1>
        <nav>
          {PAGES.map(([id, label]) => (
            <button key={id} className={page === id ? "active" : ""} onClick={() => setPage(id)}>{label}</button>
          ))}
        </nav>
        <div className="status">
          {status?.down ? <span className="error">backend offline</span> : status && (
            <>
              <span className={status.stockfish ? "ok" : "error"}>Stockfish {status.stockfish ? "✓" : "✗"}</span>
              <span className={status.llm ? "ok" : "muted"}>Claude {status.llm ? "✓" : "off (templates)"}</span>
            </>
          )}
        </div>
      </header>
      <main>
        {needsUser ? <p>Connect an account first.</p> : (
          <>
            {page === "connect" && <Connect user={user} setUser={setUser} />}
            {page === "repertoire" && <Repertoire user={user} repertoires={repertoires} reload={reloadReps} />}
            {page === "deviations" && <Deviations repertoires={repertoires} />}
            {page === "report" && <Report user={user} />}
            {page === "scout" && <Scout user={user} />}
            {page === "train" && <Train user={user} />}
            {page === "progress" && <Progress user={user} />}
          </>
        )}
      </main>
    </div>
  );
}
