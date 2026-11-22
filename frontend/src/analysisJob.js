import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api.js";

// Game fetching + analysis runs on the server as a background job. This hook lives in App,
// so it keeps polling while the user moves between pages; the top bar shows the progress.
// When a job finishes it fires "secondmind:analysis-done" so open pages can reload.
export function useAnalysisJob(user) {
  const [job, setJob] = useState(null);
  const [seen, setSeen] = useState(false); // the user has looked at the finished result
  const last = useRef(null);

  // Resume after a reload: a job may still be running on the server.
  useEffect(() => {
    if (!user) { setJob(null); return; }
    api.get("/analyze/status").then((j) => {
      setJob(j.state === "idle" ? null : j);
      setSeen(j.state !== "running"); // only announce jobs that finish while the app is open
    }).catch(() => {});
  }, [user]);

  useEffect(() => {
    if (job?.state !== "running") return undefined;
    const t = setInterval(() => {
      api.get("/analyze/status").then(setJob).catch(() => {});
    }, 1500);
    return () => clearInterval(t);
  }, [job?.state]);

  useEffect(() => {
    if (last.current === "running" && job?.state === "done") {
      window.dispatchEvent(new CustomEvent("secondmind:analysis-done", { detail: job }));
    }
    last.current = job?.state;
  }, [job?.state]); // eslint-disable-line react-hooks/exhaustive-deps

  const start = useCallback(async () => {
    setSeen(false);
    const j = await api.post("/analyze/start", { max_games: 200 });
    setJob(j);
    return j;
  }, []);

  // Rebuild only the gap report and quizzes (no new download).
  const startReport = useCallback(async () => {
    setSeen(false);
    const j = await api.post("/report/rebuild", {});
    setJob(j);
    return j;
  }, []);

  return { job, start, startReport, seen, markSeen: () => setSeen(true) };
}

// Call fn whenever a background analysis finishes.
export function useOnAnalysisDone(fn) {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => {
    const h = (e) => ref.current(e.detail);
    window.addEventListener("secondmind:analysis-done", h);
    return () => window.removeEventListener("secondmind:analysis-done", h);
  }, []);
}
