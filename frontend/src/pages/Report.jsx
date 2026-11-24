import { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import Board, { arrow } from "../components/Board.jsx";
import PageHero from "../components/PageHero.jsx";
import { useOnAnalysisDone } from "../analysisJob.js";
import { ARROW } from "../components/arrowColors.js";

const BADGE = { master: "master choice", engine: "engine choice", repertoire: "repertoire move" };
const KIND = { mistake: "mistake", deviation: "out of book", gambit_deviation: "gambit error", defender_trap: "trap", gambit_note: "gambit note" };

// Gap report: your costliest opening habits, each with the better move and a checked explanation.
// The report is built in the background after every game fetch and saved, so this page opens
// instantly; "Rebuild" redoes it in the background (progress shows in the top bar).
export default function Report({ analysis, goDeviations }) {
  const [saved, setSaved] = useState(null); // {report, leaks}
  const [sel, setSel] = useState(0);
  const [error, setError] = useState(null);

  const load = useCallback(() => api.get("/report/saved").then(setSaved).catch((e) => setError(e.message)), []);
  useEffect(() => { load(); }, [load]);
  useOnAnalysisDone(() => { load(); setSel(0); });
  // Seeing the result here clears the "ready" pill in the top bar.
  useEffect(() => { if (analysis.job?.state === "done") analysis.markSeen(); }, [analysis.job?.state]); // eslint-disable-line react-hooks/exhaustive-deps

  const job = analysis.job;
  const running = job?.state === "running";
  async function rebuild() {
    setError(null);
    try {
      await analysis.startReport();
    } catch (e) {
      setError(e.message);
    }
  }

  if (!saved) return <p className="muted">Loading…</p>;
  const report = saved.report;
  const items = report?.leaks || [];

  if (!items.length) {
    const noGames = !saved.leaks;
    return (
      <section>
        <PageHero title="Gap report" fen="rnbqkb1r/pppp1ppp/5n2/4p3/2B1P3/8/PPPP1PPP/RNBQK1NR w KQkq - 2 3"
          arrows={[["d1", "f3", ARROW.played], ["d2", "d3", ARROW.good]]}
          text={running
            ? "Your report is being prepared in the background. You can use other pages meanwhile; it appears here when it is ready."
            : noGames
              ? "Your costliest opening habits, ranked by how often they happen and how much they cost, with the move to play instead. Fetch your games first: the report is then built automatically."
              : "No costly opening habits were found in your games. Well played! Fetch more games later to check again."}
          steps={[["Fetch your games", "On the Deviations page (runs in the background)."],
            ["Report builds itself", "Stockfish finds the moves that lose the most, again and again."],
            ["Learn the fix", "Each leak shows your move in red and the better move in green."]]}>
          {running && <JobBar job={job} />}
          {!running && noGames && <button className="primary big" onClick={goDeviations}>Fetch my games</button>}
          {!running && !noGames && <button className="big outline" onClick={rebuild}>Build the report again</button>}
          {error && <div className="alert">{error}</div>}
        </PageHero>
      </section>
    );
  }

  const item = items[Math.min(sel, items.length - 1)];
  const aiItems = items.filter((x) => x.generated_by === "llm").length;
  return (
    <section className="report-page fade-in">
      <div className="page-head">
        <div>
          <h2>Gap report</h2>
          <p className="muted small">
            {items.filter((x) => !x.is_gambit_note).length} habits to fix · built {ago(report.built_at)}
            {aiItems ? ` · ${aiItems} explained by AI, fact-checked` : " · explanations from checked templates"}
          </p>
        </div>
        <button onClick={rebuild} disabled={running}>{running ? `Rebuilding… ${job.percent}%` : "Rebuild"}</button>
      </div>
      {error && <div className="alert">{error}</div>}
      <div className="rp-grid">
        <ol className="rp-list">
          {items.map((l, i) => (
            <li key={i}>
              <button className={`rp-item ${i === sel ? "on" : ""}`} onClick={() => setSel(i)}>
                <span className="rp-rank">{l.is_gambit_note ? "♟" : i + 1}</span>
                <span className="rp-main">
                  <b>{l.opening.split(":")[0]}</b>
                  <span className="muted small">
                    {l.is_gambit_note ? "gambit note" : <>you play <span className="bad">{l.played_san}</span> · {l.frequency}× · −{(l.eval_loss / 100).toFixed(1)}</>}
                  </span>
                </span>
                <span className={`tag ${l.kind}`}>{KIND[l.kind] || l.kind}</span>
              </button>
            </li>
          ))}
        </ol>
        <div className="rp-detail">
          <Board fen={item.position_fen} orientation={item.color} explore={false} max={460} canDrag={() => false}
            arrows={[arrow(item.played, ARROW.played), arrow(item.recommended, ARROW.good)].filter(Boolean)} />
          <div className="rp-text">
            <h3>{item.opening}</h3>
            {!item.is_gambit_note && (
              <p className="rp-moves">
                You play <b className="bad">{item.played_san}</b> → better <b className="good">{item.recommended_san}</b>{" "}
                {item.recommended_source && <span className="badge">{BADGE[item.recommended_source]}</span>}
                {item.verified && <span className="badge engine-badge">checked by Stockfish</span>}
              </p>
            )}
            {!item.is_gambit_note && (
              <p className="muted small">Played {item.frequency} time{item.frequency === 1 ? "" : "s"}, costing about {(item.eval_loss / 100).toFixed(2)} pawns each time.</p>
            )}
            <p>{item.explanation}</p>
            {item.plan && <p className="rp-plan"><b>Plan:</b> {item.plan}</p>}
            {item.memory_aid && <p className="rp-aid">💡 {item.memory_aid}</p>}
            {item.citations.length > 0 && (
              <ul className="cites">{item.citations.map((c) => <li key={c.id}>[{c.id}] {c.title}</li>)}</ul>
            )}
            <p className="muted small">{item.generated_by === "llm" ? "Written by AI; every move and source was checked." : "Written from Stockfish's numbers (template)."}</p>
          </div>
        </div>
      </div>
    </section>
  );
}

function JobBar({ job }) {
  return (
    <div className="job-progress big" role="status" aria-live="polite">
      <div className="job-progress-top"><span>{job.message}</span><b>{job.percent}%</b></div>
      <div className="job-progress-bar"><span style={{ width: `${Math.max(3, job.percent)}%` }} /></div>
    </div>
  );
}

function ago(iso) {
  if (!iso) return "earlier";
  const min = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (min < 1) return "just now";
  if (min < 60) return `${min} min ago`;
  const h = Math.round(min / 60);
  return h < 24 ? `${h} h ago` : `${Math.round(h / 24)} d ago`;
}
