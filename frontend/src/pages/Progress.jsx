import { useEffect, useState } from "react";
import { api } from "../api.js";

// Page 5: progress metrics (leaks, repeat-mistake rate, opening loss, quiz accuracy).
export default function Progress({ user }) {
  const [p, setP] = useState(null);
  const [leaks, setLeaks] = useState([]);

  useEffect(() => {
    api.get(`/progress?user_id=${user.id}`).then(setP);
    api.get(`/leaks?user_id=${user.id}`).then(setLeaks);
  }, [user]);

  if (!p) return <p>Loading…</p>;
  const tiles = [
    ["Open leaks", p.open_leaks],
    ["Plugged leaks", p.plugged_leaks],
    ["Avg opening loss", `${(p.avg_opening_loss_cp / 100).toFixed(2)} pawns`],
    ["Repeat-mistake rate", `${Math.round(p.repeat_mistake_rate * 100)}%`],
    ["Quizzes", p.quizzes],
    ["Quiz accuracy", p.quiz_accuracy == null ? "–" : `${Math.round(p.quiz_accuracy * 100)}%`],
  ];
  const max = Math.max(1, ...leaks.map((l) => l.frequency * Math.max(l.eval_loss_cp, 1)));
  return (
    <section>
      <h2>Progress</h2>
      <div className="tiles">{tiles.map(([k, v]) => <div key={k} className="tile"><small>{k}</small><b>{v}</b></div>)}</div>
      <h3>Leak impact (frequency × loss)</h3>
      {leaks.filter((l) => l.kind !== "gambit_note").map((l) => (
        <div key={l.id} className="barrow">
          <span className="barlabel">{l.opening?.split(":")[0]} · {l.played_san}</span>
          <span className="bar" style={{ width: `${(100 * l.frequency * Math.max(l.eval_loss_cp, 1)) / max}%` }} />
          <span className="muted">{l.status}</span>
        </div>
      ))}
    </section>
  );
}
