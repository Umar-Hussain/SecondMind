import { useEffect, useState } from "react";
import { api } from "../api.js";
import PageHero from "../components/PageHero.jsx";

// Progress: headline numbers, the leaks that cost the most (frequency × loss) and a plain
// explanation of each number. With no games analysed yet it shows an intro panel instead.
const STATUS = { open: "still happening", improving: "improving", plugged: "fixed" };

export default function Progress({ user }) {
  const [p, setP] = useState(null);
  const [leaks, setLeaks] = useState([]);

  useEffect(() => {
    api.get("/progress").then(setP).catch(() => setP({}));
    api.get("/leaks").then(setLeaks).catch(() => setLeaks([]));
  }, [user]);

  if (!p) return <p className="muted">Loading…</p>;
  const real = leaks.filter((l) => l.kind !== "gambit_note");
  if (!real.length && !p.quizzes) {
    return (
      <section>
        <PageHero title="Progress" fen="r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/2NP1N2/PPP2PPP/R1BQK2R b KQkq - 0 5"
          text="Once your games are analysed, this page tracks how many opening leaks you still have, how many you have fixed, and how your quiz accuracy improves."
          steps={[["Fetch your games", "On the Deviations page."],
            ["Train", "Answer the quizzes made from your leaks."],
            ["Watch the numbers", "Leaks move from “still happening” to “fixed” as your new games improve."]]} />
      </section>
    );
  }

  const tiles = [
    ["Open leaks", p.open_leaks ?? 0, "bad"],
    ["Fixed leaks", p.plugged_leaks ?? 0, "good"],
    ["Average opening loss", `${((p.avg_opening_loss_cp || 0) / 100).toFixed(2)}`, "", "pawns per leak"],
    ["Repeat-mistake rate", `${Math.round((p.repeat_mistake_rate || 0) * 100)}%`, ""],
    ["Quizzes", p.quizzes ?? 0, ""],
    ["Quiz accuracy", p.quiz_accuracy == null ? "–" : `${Math.round(p.quiz_accuracy * 100)}%`, "good"],
  ];
  const impact = (l) => l.frequency * Math.max(l.eval_loss_cp, 1);
  const max = Math.max(1, ...real.map(impact));
  return (
    <section className="progress-page fade-in">
      <h2>Progress</h2>
      <div className="pg-tiles">
        {tiles.map(([k, v, tone, sub]) => (
          <div key={k} className={`pg-tile ${tone}`}><small>{k}</small><b>{v}</b>{sub && <span className="muted small">{sub}</span>}</div>
        ))}
      </div>
      <div className="pg-grid">
        <div className="pg-panel">
          <h3>Leaks that cost you the most</h3>
          <p className="muted small">Longer bar = happens more often and loses more.</p>
          {real.slice(0, 14).map((l) => (
            <div key={l.id} className="pg-row">
              <span className="pg-label" title={l.opening}>{l.opening?.split(":")[0]} · <b>{l.played_san}</b></span>
              <span className="pg-track"><span className={`pg-fill ${l.status}`} style={{ width: `${(100 * impact(l)) / max}%` }} /></span>
              <span className={`pg-status ${l.status}`}>{STATUS[l.status] || l.status}</span>
            </div>
          ))}
          {!real.length && <p className="muted">No leaks found. Nice!</p>}
        </div>
        <div className="pg-panel">
          <h3>What the numbers mean</h3>
          <dl className="pg-help">
            <dt>Open leaks</dt><dd>Opening moves that cost you and that you still play in recent games.</dd>
            <dt>Fixed leaks</dt><dd>Leaks that have not shown up in your last games any more.</dd>
            <dt>Average opening loss</dt><dd>How much a leak costs on average, in pawns (1.00 = a whole pawn).</dd>
            <dt>Repeat-mistake rate</dt><dd>How often you make the same opening mistake again. Lower is better.</dd>
            <dt>Quiz accuracy</dt><dd>Share of training quizzes you answered correctly.</dd>
          </dl>
        </div>
      </div>
    </section>
  );
}
