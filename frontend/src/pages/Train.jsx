import { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import Board, { arrow } from "../components/Board.jsx";
import PageHero from "../components/PageHero.jsx";
import { useOnAnalysisDone } from "../analysisJob.js";
import { ARROW } from "../components/arrowColors.js";

// Train: quizzes made from the positions where your games went wrong. Answer by playing the
// move on the board; spaced repetition brings each quiz back just before you would forget it.
// Quizzes are created automatically after every game fetch; "Create more" adds new ones.
export default function Train({ goDeviations }) {
  const [quiz, setQuiz] = useState(undefined); // undefined = loading, null = nothing due
  const [result, setResult] = useState(null);
  const [answer, setAnswer] = useState(null); // the move the user played
  const [summary, setSummary] = useState(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState(null);

  const loadSummary = useCallback(() => api.get("/quiz/summary").then(setSummary).catch(() => {}), []);
  const next = useCallback(async () => {
    setResult(null);
    setAnswer(null);
    const res = await api.get("/quiz/next");
    setQuiz(res.quiz);
    loadSummary();
  }, [loadSummary]);

  useEffect(() => { next(); }, [next]);
  useOnAnalysisDone(() => next());

  async function generate() {
    setBusy(true);
    setNote(null);
    try {
      const res = await api.post("/quiz/generate");
      setNote(res.created ? `${res.created} new quiz${res.created === 1 ? "" : "zes"} ready.` : "No new quizzes: every open leak already has one.");
      await next();
    } catch (e) {
      setNote(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function onMove(m) {
    if (!quiz || result || m.reset) return;
    setAnswer(m);
    setResult(await api.post(`/quiz/${quiz.id}/answer`, { move_uci: m.uci }));
    loadSummary();
  }

  if (quiz === undefined) return <p className="muted">Loading…</p>;
  const s = summary || {};
  const accuracy = s.answered ? Math.round((100 * s.correct) / s.answered) : null;

  if (!quiz) {
    const noLeaks = !s.open_leaks;
    return (
      <section>
        <PageHero title="Train" fen="rnbqkbnr/pp2pppp/2p5/3p4/3PP3/8/PPP2PPP/RNBQKBNR w KQkq - 0 3"
          arrows={[["e4", "e5", ARROW.good]]}
          text={noLeaks
            ? "Short quizzes built from the positions where your own games went wrong. Fetch your games first: quizzes are then created automatically."
            : s.total
              ? `All caught up! ${s.total} quiz${s.total === 1 ? "" : "zes"} in your deck${s.next_due ? `, next one due ${when(s.next_due)}` : ""}.`
              : "Your games have been analysed. Create quizzes from your leaks to start training."}
          steps={[["Quizzes from your games", "Each one is a position where you went wrong."],
            ["Answer on the board", "Play the move you think is right."],
            ["Review on time", "Right answers come back later, wrong ones sooner."]]}>
          {noLeaks
            ? <button className="primary big" onClick={goDeviations}>Fetch my games</button>
            : <button className="primary big" onClick={generate} disabled={busy}>{busy ? "Creating quizzes…" : s.total ? "Create more quizzes" : "Create quizzes"}</button>}
          {note && <p className="muted">{note}</p>}
          {s.answered > 0 && <TrainStats s={s} accuracy={accuracy} />}
        </PageHero>
      </section>
    );
  }

  const orientation = quiz.fen.split(" ")[1] === "b" ? "black" : "white";
  const arrows = result ? [
    !result.correct && answer ? arrow(answer.uci, ARROW.played) : null,
    arrow(result.correct_move, ARROW.good),
  ].filter(Boolean) : [];
  return (
    <section className="train-page fade-in">
      <div className="page-head">
        <h2>Train</h2>
        <TrainStats s={s} accuracy={accuracy} />
      </div>
      <div className="tr-grid">
        <Board key={quiz.id} fen={quiz.fen} orientation={orientation} explore={!result} onMove={onMove} arrows={arrows} max={560}
          canDrag={result ? () => false : (p) => p[0] === orientation[0]} />
        <div className="tr-panel">
          <p className="tr-turn">{orientation === "white" ? "White" : "Black"} to move</p>
          <p className="tr-question">{quiz.question}</p>
          {!result && <p className="muted">Play your answer on the board.</p>}
          {result && (
            <div className={`tr-result ${result.correct ? "ok" : "ko"}`} role="status">
              <p className="tr-verdict">{result.correct ? "✓ Correct!" : `✗ Not quite. The answer is ${result.correct_san}.`}</p>
              {!result.correct && answer && <p className="small">You played <b className="bad">{answer.san}</b> (red arrow); the green arrow shows <b className="good">{result.correct_san}</b>.</p>}
              {result.explanation && <p className="muted small">{result.explanation}</p>}
              <p className="muted small">This quiz comes back {result.interval_days <= 1 ? "tomorrow" : `in ${result.interval_days} days`}.</p>
              <button className="primary" onClick={next}>Next quiz</button>
            </div>
          )}
          {s.due > 1 && !result && <p className="muted small">{s.due - 1} more due after this one.</p>}
        </div>
      </div>
    </section>
  );
}

function TrainStats({ s, accuracy }) {
  return (
    <div className="tr-stats">
      <span><b>{s.due ?? 0}</b> due</span>
      <span><b>{s.total ?? 0}</b> in deck</span>
      <span><b>{accuracy == null ? "–" : `${accuracy}%`}</b> correct</span>
    </div>
  );
}

function when(iso) {
  const h = Math.round((new Date(iso).getTime() - Date.now()) / 3600000);
  if (h < 1) return "within the hour";
  if (h < 24) return `in ${h} h`;
  return `in ${Math.round(h / 24)} days`;
}
