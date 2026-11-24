import { useCallback, useEffect, useState } from "react";
import { Chess } from "chess.js";
import { api, fenKey } from "../api.js";
import Board, { arrow } from "../components/Board.jsx";
import PageHero from "../components/PageHero.jsx";
import CompareView from "../components/CompareView.jsx";
import { useOnAnalysisDone } from "../analysisJob.js";
import { ARROW } from "../components/arrowColors.js";

// Deviations page as a guided flow:
//   1. link a Lichess and/or Chess.com username (public names only, never a password);
//   2. fetch the games and check them against every repertoire (a background job: the user
//      can leave the page, the top bar shows progress, this page reloads when it finishes);
//   3. review: the openings you actually play, whether a repertoire covers them, and for each
//      opening the exact position where the game left the repertoire, shown on the board.
// Red arrow = what you played, green = what your repertoire says, blue = the engine-checked
// recommendation, orange = an opponent move your repertoire has no answer to yet.
const RED = ARROW.played;
const GREEN = ARROW.good;
const BLUE = ARROW.engine;
const ORANGE = ARROW.gap;

const STATE_LABEL = {
  in_book: "stayed in your repertoire",
  you_left: "you left your repertoire",
  opponent: "opponent surprised you",
  none: "no repertoire",
};

// Example position for the intro panels: 1.e4 c6 2.d4 d5 3.e5, your Bf5 vs the Bg4 you played.
const HERO_FEN = "rnbqkbnr/pp2pppp/2p5/3pP3/3P4/8/PPP2PPP/RNBQKBNR b KQkq - 0 3";

export default function Deviations({ user, setUser, onOpen, goLibrary, analysis }) {
  const linked = Boolean(user.lichess_username || user.chesscom_username);
  const [editing, setEditing] = useState(!linked);
  const [overview, setOverview] = useState(null);
  const [error, setError] = useState(null);
  const [sel, setSel] = useState(null); // index of the selected opening
  const [exitIdx, setExitIdx] = useState(0);
  const [colour, setColour] = useState("all");

  const loadOverview = useCallback(() => api.get("/my-openings").then(setOverview).catch((e) => setError(e.message)), []);
  useEffect(() => { loadOverview(); }, [loadOverview]);

  useOnAnalysisDone(() => { loadOverview(); setSel(null); });
  // Seeing the finished result on this page clears the "Games ready" pill in the top bar.
  useEffect(() => { if (analysis.job?.state !== "running") analysis.markSeen(); }, [analysis.job?.state]); // eslint-disable-line react-hooks/exhaustive-deps

  const job = analysis.job;
  const busy = job?.state === "running";
  const summary = job?.state === "done" ? job.summary : null;
  async function fetchGames() {
    setError(null);
    try {
      await analysis.start();
    } catch (e) {
      setError(e.message);
    }
  }

  const step = !linked ? 1 : !overview?.games ? 2 : 3;
  const openings = (overview?.openings || []).filter((o) => colour === "all" || o.color === colour);
  const opening = sel !== null ? openings[sel] : null;

  return (
    <section className="dev-page fade-in">
      <h2>Your openings vs your repertoire</h2>
      <ol className="dev-steps" aria-label="Steps">
        {["Link your account", "Fetch your games", "See what to fix"].map((t, i) => (
          <li key={t} className={step === i + 1 ? "on" : step > i + 1 ? "done" : ""}>
            <span>{step > i + 1 ? "✓" : i + 1}</span>{t}
          </li>
        ))}
      </ol>

      {editing && step === 1 ? (
        <PageHero title="Which account do you play on?" fen={HERO_FEN} orientation="black"
          arrows={[["c8", "g4", ARROW.played], ["c8", "f5", ARROW.good]]}
          text="SecondMind downloads your recent games, finds the openings you really play and shows the exact move where each game left your repertoire."
          steps={[["Link your account", "Your public Lichess or Chess.com name. We never ask for a password."],
            ["Fetch your games", "Runs in the background, so you can keep using the app."],
            ["Fix your leaks", "See your move next to your repertoire move, with Stockfish's verdict."]]}>
          <AccountForm bare user={user} onSaved={(u) => { setUser({ ...user, ...u }); setEditing(false); }} onCancel={null} />
        </PageHero>
      ) : editing ? (
        <AccountForm user={user} onSaved={(u) => { setUser({ ...user, ...u }); setEditing(false); }}
          onCancel={() => setEditing(false)} />
      ) : (
        <div className="dev-accounts">
          <div className="dev-acc-names">
            {user.lichess_username && <span className="acc-chip lichess">Lichess · <b>{user.lichess_username}</b></span>}
            {user.chesscom_username && <span className="acc-chip chesscom">Chess.com · <b>{user.chesscom_username}</b></span>}
            <button className="link" onClick={() => setEditing(true)}>Change</button>
          </div>
          {step === 3 && <button className="primary" onClick={fetchGames} disabled={busy}>
            {busy ? "Fetching and checking games…" : overview?.games ? "Fetch new games" : "Fetch my games"}
          </button>}
        </div>
      )}
      {busy && <JobProgress job={job} />}
      {job?.state === "error" && <div className="alert">The fetch failed: {job.error}</div>}
      {summary && (
        <p className="ok small">
          {summary.games_fetched} games fetched ({summary.games_new} new). Checked against {summary.repertoires_analyzed} repertoire(s).
        </p>
      )}
      {summary?.warnings?.map((w) => <div key={w} className="alert">{w}</div>)}
      {error && <div className="alert">{error}</div>}
      {step === 2 && !editing && (
        <PageHero title={busy ? "Fetching your games…" : "Ready to fetch your games"} fen={HERO_FEN} orientation="black"
          arrows={[["c8", "g4", ARROW.played], ["c8", "f5", ARROW.good]]}
          text={busy
            ? "This runs on our server. Feel free to open other pages: the bar at the top shows the progress and this page fills in by itself."
            : "We download up to 200 of your recent games, check them with Stockfish and compare every opening with your repertoires."}
          steps={[["Download", "Your recent rated games from the linked sites."],
            ["Check", "Stockfish looks at each opening move you played."],
            ["Compare", "Every game is matched against your repertoires."]]}>
          {!busy && <button className="primary big" onClick={fetchGames}>Fetch my games</button>}
          {busy && <JobProgress job={job} big />}
        </PageHero>
      )}

      {step === 3 && (
        <>
          {overview.repertoires === 0 && (
            <div className="dev-empty">
              You have no repertoire yet, so every game shows as "no repertoire".{" "}
              <button className="link" onClick={goLibrary}>Pick one from the library</button> or import your own.
            </div>
          )}
          <div className="dev-grid">
            <div className="dev-list">
              <div className="dev-list-head">
                <span>{overview.games} games · {overview.openings.length} openings</span>
                <select value={colour} onChange={(e) => { setColour(e.target.value); setSel(null); }} aria-label="Colour">
                  <option value="all">Both colours</option>
                  <option value="white">As White</option>
                  <option value="black">As Black</option>
                </select>
              </div>
              <ul>
                {openings.map((o, i) => (
                  <li key={o.color + o.opening}>
                    <button className={`dev-op ${sel === i ? "on" : ""}`} onClick={() => {
                      setSel(i);
                      setExitIdx(0);
                      // On phones the detail sits under the list: bring it into view.
                      if (window.innerWidth < 860) setTimeout(() => document.querySelector(".dev-detail")?.scrollIntoView({ behavior: "smooth" }), 50);
                    }}>
                      <span className={`dev-side ${o.color}`} aria-label={`as ${o.color}`}>{o.color === "white" ? "♔" : "♚"}</span>
                      <span className="dev-op-main">
                        <b>{o.opening}</b>
                        <span className="muted small">{o.games} game{o.games === 1 ? "" : "s"} as {o.color} · {o.repertoire_name || "not in a repertoire"}</span>
                        <StateBar states={o.states} />
                      </span>
                      <Status o={o} />
                    </button>
                  </li>
                ))}
              </ul>
            </div>
            <div className="dev-detail">
              {opening ? (
                <OpeningDetail key={opening.color + opening.opening} o={opening} exitIdx={exitIdx} setExitIdx={setExitIdx}
                  onOpen={onOpen} goLibrary={goLibrary} reload={loadOverview} />
              ) : (
                <div className="dev-pick">
                  <p className="dev-pick-title">Pick an opening</p>
                  <p className="muted">
                    Each one shows where your games left your repertoire, which move you played and which move you
                    should have played.
                  </p>
                  <ul className="dev-legend">
                    <li><i style={{ background: "var(--success)" }} />stayed in your repertoire</li>
                    <li><i style={{ background: "var(--error)" }} />you left your repertoire</li>
                    <li><i style={{ background: "var(--warning)" }} />opponent played a move you have not prepared</li>
                    <li><i style={{ background: "var(--text-tertiary)" }} />no repertoire covers it</li>
                  </ul>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </section>
  );
}

// Step 1: public usernames only.
function AccountForm({ user, onSaved, onCancel, bare = false }) {
  const [form, setForm] = useState({ lichess_username: user.lichess_username || "", chesscom_username: user.chesscom_username || "" });
  const [error, setError] = useState(null);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  async function save(e) {
    e.preventDefault();
    const body = { lichess_username: form.lichess_username.trim(), chesscom_username: form.chesscom_username.trim() };
    if (!body.lichess_username && !body.chesscom_username) {
      setError("Enter at least one username.");
      return;
    }
    try {
      onSaved(await api.patch("/auth/me", body));
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <form className="dev-account-form" onSubmit={save}>
      {!bare && <p className="dev-pick-title">Which account do you play on?</p>}
      <p className="muted small">We only need your public username to download your games. We never ask for your chess-site password.</p>
      <div className="dev-acc-inputs">
        <label>Lichess username<input value={form.lichess_username} onChange={set("lichess_username")} placeholder="your Lichess name" /></label>
        <label>Chess.com username<input value={form.chesscom_username} onChange={set("chesscom_username")} placeholder="your Chess.com name" /></label>
      </div>
      {error && <div className="alert">{error}</div>}
      <div className="dev-acc-actions">
        <button className="primary">Save and continue</button>
        {onCancel && <button type="button" className="ghost" onClick={onCancel}>Cancel</button>}
      </div>
    </form>
  );
}

// A thin stacked bar: how this opening's games ended up (in book / you left / opponent / none).
function StateBar({ states }) {
  const total = Object.values(states).reduce((a, b) => a + b, 0) || 1;
  return (
    <span className="dev-bar" aria-hidden="true">
      {["in_book", "you_left", "opponent", "none"].map((k) => states[k] > 0 && (
        <span key={k} className={`seg ${k}`} style={{ width: `${(100 * states[k]) / total}%` }} />
      ))}
    </span>
  );
}

function Status({ o }) {
  if (o.states.none === o.games) return <span className="tag">no repertoire</span>;
  if (o.states.you_left) return <span className="tag bad">{o.states.you_left} to fix</span>;
  if (o.states.opponent) return <span className="tag warn">{o.states.opponent} gap{o.states.opponent === 1 ? "" : "s"}</span>;
  return <span className="tag good">on track</span>;
}

function OpeningDetail({ o, exitIdx, setExitIdx, onOpen, goLibrary, reload }) {
  const exit = o.exits[exitIdx];
  const [detail, setDetail] = useState(null);
  const [msg, setMsg] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setDetail(null);
    setMsg(null);
    if (exit?.deviation_id) api.get(`/deviations/${exit.deviation_id}`).then(setDetail).catch(() => setDetail(null));
  }, [exit?.deviation_id, exit?.fen, exit?.played]);

  const wdl = o.results;
  const header = (
    <div className="dev-detail-head">
      <h3>{o.opening}</h3>
      <p className="muted small">
        As {o.color} · {o.games} game{o.games === 1 ? "" : "s"} · <span className="good">{wdl.win} won</span> ·{" "}
        {wdl.draw} drawn · <span className="bad">{wdl.loss} lost</span>
      </p>
    </div>
  );

  if (o.states.none === o.games) {
    return (
      <div className="dev-panel">
        {header}
        <Board fen={fenAfter(o.sample_line)} orientation={o.color} explore={false} max={boardMax()} canDrag={() => false} />
        <p>None of your repertoires covers this opening yet. A typical game went <b>{o.sample_line}</b>.</p>
        <button className="primary" onClick={goLibrary}>Find a repertoire for it</button>
      </div>
    );
  }
  if (!exit) {
    return (
      <div className="dev-panel">
        {header}
        <p className="ok">Every game in this opening stayed inside your repertoire ({o.repertoire_name}). Nothing to fix here.</p>
        {o.repertoire_id && <button onClick={() => onOpen(o.repertoire_id)}>Practise {o.repertoire_name}</button>}
      </div>
    );
  }

  const youLeft = exit.state === "you_left";
  const rec = detail?.recommended_move;
  const arrows = youLeft
    ? [arrow(exit.played, RED), arrow(exit.repertoire_move, GREEN), rec && rec !== exit.repertoire_move ? arrow(rec, BLUE) : null]
    : [arrow(exit.played, ORANGE)];

  async function addReply() {
    setError(null);
    try {
      await api.patch(`/repertoires/${exit.repertoire_id}/nodes`, { fen_key: exit.fen_key, add_opponent_move: exit.played });
      await api.patch(`/repertoires/${exit.repertoire_id}/nodes`, { fen_key: keyAfter(exit.fen, exit.played), user_move: exit.suggested_reply });
      setMsg(`Added ${exit.played_san} with your reply ${exit.suggested_san} to ${o.repertoire_name}.`);
      reload();
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <div className="dev-panel">
      {header}
      {o.exits.length > 1 && (
        <div className="dev-exits" role="tablist" aria-label="Where games left the repertoire">
          {o.exits.map((e, i) => (
            <button key={e.fen + e.played} role="tab" aria-selected={i === exitIdx} className={i === exitIdx ? "on" : ""} onClick={() => setExitIdx(i)}>
              {e.state === "you_left" ? "You: " : "Opponent: "}{e.played_san} <span className="muted">×{e.games}</span>
            </button>
          ))}
        </div>
      )}
      {!youLeft && <Board fen={exit.fen} orientation={o.color} explore={false} max={boardMax()} arrows={arrows.filter(Boolean)} canDrag={() => false} />}
      <p className="dev-line muted small">After {exit.line || "the first move"}</p>
      {youLeft ? (
        <>
          {/* Split screen: your move and how your games went on | your repertoire line; then Stockfish's suggestion. */}
          <CompareView key={exit.fen + exit.played} repertoireId={exit.repertoire_id} fen={exit.fen} played={exit.played} color={o.color} />
          <p className="dev-say">
            In <b>{exit.games}</b> game{exit.games === 1 ? "" : "s"} you played <b className="bad">{exit.played_san}</b> here.
            Your repertoire plays <b className="good">{exit.repertoire_san}</b>.
          </p>
          {detail && rec && rec !== exit.repertoire_move && (
            <p>Stockfish and the master games suggest <b style={{ color: "var(--info)" }}>{detail.recommended_san}</b> as an option too.</p>
          )}
          {!detail && exit.deviation_id && <p className="muted small">Writing the explanation…</p>}
          {detail?.explanation && <p>{detail.explanation}</p>}
          {detail?.plan && <p className="muted"><i>{detail.plan}</i></p>}
          {detail?.game_links?.length > 0 && (
            <p className="small">Your games: {detail.game_links.map((g, i) => <a key={g} href={g} target="_blank" rel="noreferrer">#{i + 1} </a>)}</p>
          )}
          <button className="primary" onClick={() => onOpen(exit.repertoire_id)}>Practise this repertoire</button>
        </>
      ) : (
        <>
          <p className="dev-say">
            In <b>{exit.games}</b> game{exit.games === 1 ? "" : "s"} your opponent played <b style={{ color: "var(--warning)" }}>{exit.played_san}</b> here,
            and your repertoire has no answer to it yet.
          </p>
          {exit.suggested_san ? (
            <>
              <p>A good reply is <b className="good">{exit.suggested_san}</b>.</p>
              <button className="primary" onClick={addReply} disabled={Boolean(msg)}>Add {exit.suggested_san} to my repertoire</button>
            </>
          ) : (
            <button onClick={() => onOpen(exit.repertoire_id)}>Open the repertoire and add a reply</button>
          )}
        </>
      )}
      {msg && <p className="ok small">{msg}</p>}
      {error && <div className="alert">{error}</div>}
      <p className="dev-key small muted">
        {youLeft
          ? <><i style={{ background: RED }} />you played <i style={{ background: GREEN }} />your repertoire {rec && rec !== exit.repertoire_move && <><i style={{ background: BLUE }} />recommended</>}</>
          : <><i style={{ background: ORANGE }} />opponent move you have not prepared</>}
      </p>
    </div>
  );
}

// Board size that fits inside the detail panel (its padding) on phones.
function boardMax() {
  return Math.min(460, window.innerWidth - 80);
}

// "1.e4 c6 2.d4" -> FEN after those moves (used for the "no repertoire" preview board).
function fenAfter(line) {
  const g = new Chess();
  for (const tok of (line || "").split(" ")) {
    const san = tok.replace(/^\d+\.(\.\.)?/, "");
    if (!san) continue;
    try { g.move(san); } catch { break; }
  }
  return g.fen();
}

function keyAfter(fen, uci) {
  const g = new Chess(fen);
  g.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] });
  return fenKey(g.fen());
}

// Live progress of the background fetch.
function JobProgress({ job, big }) {
  return (
    <div className={`job-progress ${big ? "big" : ""}`} role="status" aria-live="polite">
      <div className="job-progress-top"><span>{job.message}</span><b>{job.percent}%</b></div>
      <div className="job-progress-bar"><span style={{ width: `${Math.max(3, job.percent)}%` }} /></div>
    </div>
  );
}
