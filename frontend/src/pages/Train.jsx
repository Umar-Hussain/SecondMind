import { useEffect, useState } from "react";
import { api } from "../api.js";
import Board from "../components/Board.jsx";

// Page 4: answer quizzes by moving a piece; SM-2 schedules the next review.
export default function Train({ user }) {
  const [quiz, setQuiz] = useState(null);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");

  async function next() {
    setResult(null);
    const res = await api.get("/quiz/next");
    setQuiz(res.quiz);
    if (!res.quiz) setNote("No quizzes due right now.");
  }

  async function generate() {
    setBusy(true);
    try {
      await api.post("/quiz/generate");
      await next();
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => { next(); }, []);

  async function onMove(m) {
    if (!quiz || result || m.reset) return;
    setResult(await api.post(`/quiz/${quiz.id}/answer`, { move_uci: m.uci }));
  }

  const orientation = quiz && quiz.fen.split(" ")[1] === "b" ? "black" : "white";
  return (
    <section>
      <h2>Train</h2>
      <button onClick={generate} disabled={busy}>{busy ? "Creating quizzes…" : "Create quizzes from my leaks"}</button>{" "}
      <button onClick={next}>Next due quiz</button>
      {!quiz && <p className="muted">{note}</p>}
      {quiz && (
        <div className="grid2">
          <Board fen={quiz.fen} orientation={orientation} explore={!result} onMove={onMove} />
          <div>
            <p><b>{quiz.question}</b></p>
            <p className="muted">Answer by moving a piece on the board.</p>
            {result && (
              <div className={`card ${result.correct ? "ok" : "ko"}`}>
                <p>{result.correct ? "✅ Correct!" : `❌ The answer was ${result.correct_san}.`}</p>
                <p className="muted">{result.explanation}</p>
                <p className="muted">Next review in {result.interval_days} day(s).</p>
                <button onClick={next}>Next</button>
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
