import { useState } from "react";
import { api } from "../api.js";
import Board, { arrow } from "../components/Board.jsx";
import PageHero from "../components/PageHero.jsx";

const BADGE = { master: "master choice", engine: "engine choice", repertoire: "repertoire move" };

// Page 2: gap report. Gambit items are shown as notes, never as blunders.
export default function Report({ user }) {
  const [report, setReport] = useState(null);
  const [sel, setSel] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function load() {
    setBusy(true);
    setError(null);
    try {
      setReport(await api.get("/report?top=8"));
      setSel(0);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const item = report?.leaks[sel];
  if (!report || report.leaks.length === 0) {
    return (
      <section>
        <PageHero title="Gap report" fen="rnbqkb1r/pppp1ppp/5n2/4p3/2B1P3/8/PPPP1PPP/RNBQK1NR w KQkq - 2 3"
          arrows={[["d1", "f3", "rgba(204,51,51,.85)"], ["d2", "d3", "rgba(21,120,27,.85)"]]}
          text={report
            ? "No opening leaks found yet. Fetch your games on the Deviations page first, then build the report again."
            : "Your most costly opening habits, ranked by how often they happen and how much they cost, with the move to play instead and a short, fact-checked explanation."}
          steps={[["Fetch your games", "On the Deviations page (runs in the background)."],
            ["Build the report", "Stockfish finds the moves that lose the most, again and again."],
            ["Learn the fix", "Each leak shows your move in red and the better move in green."]]}>
          <button className="primary big" onClick={load} disabled={busy}>{busy ? "Building report…" : "Build my report"}</button>
          {error && <div className="alert">{error}</div>}
        </PageHero>
      </section>
    );
  }
  return (
    <section>
      <div className="page-head">
        <h2>Gap report</h2>
        <button onClick={load} disabled={busy}>{busy ? "Building report…" : "Rebuild"}</button>
      </div>
      {error && <div className="alert">{error}</div>}
      {report && (
        <div className="grid2">
          <ul className="leaklist">
            {report.leaks.map((l, i) => (
              <li key={i} className={i === sel ? "selected" : ""} onClick={() => setSel(i)}>
                {l.is_gambit_note ? <span className="tag gambit">gambit note</span> : <span className={`tag ${l.kind}`}>{l.kind.replace("_", " ")}</span>}{" "}
                <b>{l.opening}</b> — {l.played_san}
                {!l.is_gambit_note && <> ×{l.frequency} · −{(l.eval_loss / 100).toFixed(2)}</>}
              </li>
            ))}
          </ul>
          {item && (
            <div className="detail">
              <Board fen={item.position_fen} orientation={item.color} explore={false}
                arrows={[arrow(item.played, "rgb(220,60,60)"), arrow(item.recommended, "rgb(40,160,80)")].filter(Boolean)} />
              {!item.is_gambit_note && (
                <p>
                  You play <b className="bad">{item.played_san}</b> · recommended <b className="good">{item.recommended_san}</b>{" "}
                  <span className="badge">{BADGE[item.recommended_source]}</span>
                  {item.verified && <span className="badge engine-badge">verified</span>}
                </p>
              )}
              <p className="muted">{item.reason}</p>
              <p>{item.explanation}</p>
              {item.plan && <p><i>{item.plan}</i></p>}
              {item.memory_aid && <p>💡 {item.memory_aid}</p>}
              {item.citations.length > 0 && (
                <ul className="cites">{item.citations.map((c) => <li key={c.id}>[{c.id}] {c.title}</li>)}</ul>
              )}
              {item.master_games.length > 0 && (
                <p className="muted">Master games: {item.master_games.map((g) => g.title).join("; ")}</p>
              )}
            </div>
          )}
        </div>
      )}
      {report && <p className="muted">Explanations by: {report.generated_by === "llm" ? "Claude (guarded)" : "templates (no API key set)"}</p>}
    </section>
  );
}
