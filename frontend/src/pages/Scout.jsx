import { useEffect, useMemo, useRef, useState } from "react";
import { Chess } from "chess.js";
import { api, fenKey } from "../api.js";
import Board from "../components/Board.jsx";
import EnginePanel from "../components/EnginePanel.jsx";
import { buildTree, positionData, scoreColor } from "../engine/openingTree.js";

// Arrow colours for suggestions (your move). Opponent moves use scoreColor().
const SUGGEST = {
  repertoire: { color: "rgba(54,146,231,0.95)", label: "Your repertoire" },
  recommended: { color: "rgba(155,199,0,0.95)", label: "Recommended" },
  weak: { color: "rgba(230,140,30,0.95)", label: "Their weak spot" },
  punish: { color: "rgba(210,70,170,0.95)", label: "Punish their mistake" },
};
const SPEEDS = ["all", "bullet", "blitz", "rapid", "classical"];

function replay(path) {
  const g = new Chess();
  for (const m of path) g.move({ from: m.uci.slice(0, 2), to: m.uci.slice(2, 4), promotion: m.uci[4] });
  return g;
}

function toPath(ucis) {
  const g = new Chess();
  const out = [];
  for (const u of ucis) {
    try {
      const mv = g.move({ from: u.slice(0, 2), to: u.slice(2, 4), promotion: u[4] });
      out.push({ uci: u, san: mv.san });
    } catch {
      break;
    }
  }
  return out;
}

function ResultBar({ win, draw, loss }) {
  const total = Math.max(1, win + draw + loss);
  return (
    <span className="wdl" title={`Their results: ${win} wins, ${draw} draws, ${loss} losses`}>
      {[["w", win], ["d", draw], ["l", loss]].map(([k, n]) =>
        n ? <span key={k} className={`wdl-${k}`} style={{ width: `${(100 * n) / total}%` }}>{(100 * n) / total >= 18 ? n : ""}</span> : null)}
    </span>
  );
}

// Prepare: explore an opponent's games on the board and see suggestions as arrows.
export default function Scout() {
  const [evaluation, setEvaluation] = useState(null); // live engine score for the board's bar
  const [opponent, setOpponent] = useState("");
  const [platform, setPlatform] = useState("lichess");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [color, setColor] = useState("white"); // the colour THEY play
  const [speed, setSpeed] = useState("all");
  const [path, setPath] = useState([]);
  const [tab, setTab] = useState("moves");
  const [hover, setHover] = useState(null);
  const [flipped, setFlipped] = useState(false);
  const [profile, setProfile] = useState(null);
  const [profileState, setProfileState] = useState("idle");
  const [briefing, setBriefing] = useState(null);
  const [briefingState, setBriefingState] = useState("idle");
  const [rep, setRep] = useState(null);
  const [rec, setRec] = useState(null);
  const cache = useRef({ rep: new Map(), rec: new Map() });

  async function load(e) {
    e?.preventDefault();
    if (!opponent.trim()) return;
    setLoading(true); setError(null); setData(null); setProfile(null); setBriefing(null); setPath([]);
    try {
      const res = await api.get(`/scout/games?opponent=${encodeURIComponent(opponent.trim())}&platform=${platform}`);
      setData(res);
      const asWhite = res.games.filter((g) => g.opp_color === "white").length;
      setColor(asWhite >= res.games.length - asWhite ? "white" : "black");
      // Engine-checked weak spots load in the background (they take a little longer).
      setProfileState("loading");
      api.get(`/scout/profile?opponent=${encodeURIComponent(opponent.trim())}&platform=${platform}`)
        .then((p) => { setProfile(p); setProfileState("done"); })
        .catch(() => setProfileState("error"));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function loadBriefing() {
    setBriefingState("loading");
    try {
      setBriefing(await api.post("/scout", { opponent: opponent.trim(), platform }));
      setBriefingState("done");
    } catch (err) {
      setBriefingState("error");
      setError(err.message);
    }
  }

  const tree = useMemo(() => (data ? buildTree(data.games, { color, speed }) : null), [data, color, speed]);
  const game = useMemo(() => replay(path), [path]);
  const fen = game.fen();
  const pos = useMemo(() => (tree ? positionData(tree, fen) : { total: 0, moves: [], games: [] }), [tree, fen]);
  const theirTurn = (game.turn() === "w") === (color === "white");
  const you = color === "white" ? "black" : "white";

  // Switching colour starts from the initial position; jumping to a line sets both at once.
  function chooseColor(c) { setColor(c); setFlipped(false); setPath([]); }

  // Your repertoire move and the recommended move, only when it is your turn.
  useEffect(() => {
    setRep(null); setRec(null);
    if (!data || theirTurn) return;
    let live = true;
    const c = cache.current;
    const key = fenKey(fen);
    (c.rep.has(key) ? Promise.resolve(c.rep.get(key)) : api.get(`/repertoire-moves?fen=${encodeURIComponent(fen)}`))
      .then((r) => { c.rep.set(key, r); if (live) setRep(r); }).catch(() => {});
    (c.rec.has(key) ? Promise.resolve(c.rec.get(key)) : api.get(`/recommend?fen=${encodeURIComponent(fen)}&depth=12`))
      .then((r) => { c.rec.set(key, r); if (live) setRec(r); }).catch(() => {});
    return () => { live = false; };
  }, [fen, theirTurn, data]);

  const weaknesses = (profile?.weaknesses || []).filter((w) => w.opp_color === color);
  const mainLines = (profile?.repeated_lines || []).filter((l) => l.color === color);

  // Suggestions (your move) — each becomes an arrow on the board.
  const suggestions = [];
  if (!theirTurn) {
    const punish = weaknesses.find((w) => {
      const g = replay(toPath([...w.path, w.move]));
      return w.punish && fenKey(g.fen()) === fenKey(fen);
    });
    if (punish) suggestions.push({ type: "punish", uci: punish.punish, san: punish.punish_san,
      why: `They play ${punish.san} here in ${punish.games} game(s); it loses about ${(punish.loss_cp / 100).toFixed(1)} pawns.` });
    (rep?.moves || []).filter((m) => m.kind === "main").forEach((m) =>
      suggestions.push({ type: "repertoire", uci: m.uci, san: m.san, why: `Your move in “${m.repertoire}”.` }));
    if (rec?.chosen_uci) suggestions.push({ type: "recommended", uci: rec.chosen_uci, san: rec.chosen_san,
      why: `${rec.chosen_source === "master" ? "Master choice" : "Engine choice"}: ${rec.reason.split(". Rejected")[0]}` });
    const weak = pos.moves.filter((m) => m.count >= 2 && m.score <= 0.4).sort((a, b) => a.score - b.score)[0];
    if (weak) suggestions.push({ type: "weak", uci: weak.uci, san: weak.san,
      why: `After ${weak.san} they scored only ${Math.round(weak.score * 100)}% (${weak.count} games).` });
  }

  // One arrow and one card per move: several reasons for the same move are merged,
  // and the arrow takes the colour of the most important reason.
  const PRIORITY = ["punish", "repertoire", "recommended", "weak"];
  const merged = [];
  for (const sug of suggestions) {
    const hit = merged.find((m) => m.uci === sug.uci);
    if (hit) hit.reasons.push(sug);
    else merged.push({ uci: sug.uci, san: sug.san, reasons: [sug] });
  }
  merged.forEach((m) => m.reasons.sort((a, b) => PRIORITY.indexOf(a.type) - PRIORITY.indexOf(b.type)));
  merged.sort((a, b) => PRIORITY.indexOf(a.reasons[0].type) - PRIORITY.indexOf(b.reasons[0].type));

  const arrows = theirTurn
    ? pos.moves.slice(0, 6).map((m) => [m.from, m.to, hover === m.uci ? "rgba(54,146,231,0.95)" : scoreColor(m.score)])
    : merged.map((m) => [m.uci.slice(0, 2), m.uci.slice(2, 4), SUGGEST[m.reasons[0].type].color]);

  function play(uci, san) { setPath([...path, { uci, san }]); }
  function jump(ucis, oppColor) {
    if (oppColor && oppColor !== color) { setColor(oppColor); setFlipped(false); }
    setPath(toPath(ucis));
    setTab("moves");
  }

  return (
    <section>
      <div className="page-head">
        <div>
          <h2>Prepare for an opponent</h2>
          <p className="muted">Load their games, walk through what they play on the board, and see what to play against it.</p>
        </div>
      </div>
      <form className="form" onSubmit={load}>
        <label>Opponent<input value={opponent} onChange={(e) => setOpponent(e.target.value)} placeholder="Lichess or Chess.com username" /></label>
        <label>Site
          <select value={platform} onChange={(e) => setPlatform(e.target.value)}>
            <option value="lichess">Lichess</option><option value="chesscom">Chess.com</option>
          </select>
        </label>
        <button className="primary" disabled={loading || !opponent.trim()}>{loading ? "Loading games…" : "Load games"}</button>
      </form>
      {error && <div className="alert">{error}</div>}

      {data && tree && (
        <div className="ws-grid">
          {/* ---------- left: filters + their moves ---------- */}
          <aside className="panel">
            <div className="panel-title">{data.opponent} <span className="muted small">· {tree.total} of {data.count} games</span></div>
            <div className="segmented full-seg">
              <button className={color === "white" ? "on" : ""} onClick={() => chooseColor("white")}>They play White</button>
              <button className={color === "black" ? "on" : ""} onClick={() => chooseColor("black")}>They play Black</button>
            </div>
            <div className="chips">
              {SPEEDS.map((s) => (
                <button key={s} className={`chip ${speed === s ? "on" : ""}`} onClick={() => setSpeed(s)}>{s}</button>
              ))}
            </div>
            <div className="segmented full-seg">
              <button className={tab === "moves" ? "on" : ""} onClick={() => setTab("moves")}>Moves</button>
              <button className={tab === "games" ? "on" : ""} onClick={() => setTab("games")}>Games <small>{pos.games.length}</small></button>
            </div>
            {tab === "moves" ? (
              <>
                <p className="muted small">{theirTurn ? `${data.opponent} to move` : "Your move — moves their opponents chose"} · {pos.total} games here</p>
                {pos.moves.length === 0 && <p className="muted small">No games went past this position.</p>}
                <table className="movestats">
                  <tbody>
                    {pos.moves.map((m) => (
                      <tr key={m.uci} onClick={() => play(m.uci, m.san)} onMouseEnter={() => setHover(m.uci)} onMouseLeave={() => setHover(null)}>
                        <td className="mv"><b>{m.san}</b></td>
                        <td className="num">{m.count}</td>
                        <td className="num muted">{Math.round(m.share * 100)}%</td>
                        <td className="bar-cell"><ResultBar win={m.win} draw={m.draw} loss={m.loss} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="muted small legend-note">Bars show <b>their</b> results: light = they won, grey = draw, dark = they lost.</p>
              </>
            ) : (
              <ul className="gamelist">
                {pos.games.slice(0, 40).map((g) => (
                  <li key={g.source + g.id}>
                    <span className={`res ${g.result}`}>{g.result === "win" ? "1" : g.result === "loss" ? "0" : "½"}</span>
                    <span className="small">{g.white} – {g.black}</span>
                    <span className="muted small">{g.speed} · {g.date}</span>
                    {g.url && <a href={g.url} target="_blank" rel="noreferrer" className="small">open ↗</a>}
                  </li>
                ))}
              </ul>
            )}
          </aside>

          {/* ---------- centre: board ---------- */}
          <div className="ws-center">
            <Board evaluation={evaluation} fen={fen} orientation={flipped ? color : you} explore={false} arrows={arrows}
              highlight={path.length ? path[path.length - 1].uci : null} onMove={(m) => !m.reset && play(m.uci, m.san)} />
            <div className="legend">
              {theirTurn ? (
                <>
                  <span><i style={{ background: scoreColor(0.7) }} />they score well</span>
                  <span><i style={{ background: scoreColor(0.5) }} />about even</span>
                  <span><i style={{ background: scoreColor(0.2) }} />they score badly</span>
                </>
              ) : Object.entries(SUGGEST).map(([k, v]) => <span key={k}><i style={{ background: v.color }} />{v.label}</span>)}
            </div>
            <div className="pathline">
              <button className="link" onClick={() => setPath([])}>start</button>
              {path.map((m, i) => (
                <button key={i} className={`link ${i === path.length - 1 ? "current" : ""}`} onClick={() => setPath(path.slice(0, i + 1))}>
                  {i % 2 === 0 ? `${i / 2 + 1}.` : ""}{m.san}
                </button>
              ))}
            </div>
            <div className="controls">
              <button onClick={() => setPath([])}>⏮ Start</button>
              <button onClick={() => setPath(path.slice(0, -1))} disabled={!path.length}>◀ Back</button>
              <button onClick={() => pos.moves[0] && play(pos.moves[0].uci, pos.moves[0].san)} disabled={!pos.moves.length}>Their main line ▶</button>
              <button onClick={() => setFlipped(!flipped)}>⇅ Flip</button>
            </div>
          </div>

          {/* ---------- right: suggestions, mistakes, lines, engine ---------- */}
          <aside className="panel">
            {!theirTurn && (
              <>
                <div className="panel-title">What to play here</div>
                {merged.length === 0 && <p className="muted small">Thinking…</p>}
                <ul className="suggest">
                  {merged.map((m) => (
                    <li key={m.uci} onClick={() => play(m.uci, m.san)} title="Play it on the board">
                      <i style={{ background: SUGGEST[m.reasons[0].type].color }} />
                      <div>
                        <b>{m.san}</b>{" "}
                        {m.reasons.map((r) => (
                          <span key={r.type} className="reason-tag" style={{ borderColor: SUGGEST[r.type].color }}>{SUGGEST[r.type].label}</span>
                        ))}
                        {m.reasons.map((r) => <p key={r.type} className="small">{r.why}</p>)}
                      </div>
                    </li>
                  ))}
                </ul>
              </>
            )}
            {theirTurn && pos.moves[0] && (
              <>
                <div className="panel-title">They usually play</div>
                <p className="small"><b>{pos.moves[0].san}</b> in {Math.round(pos.moves[0].share * 100)}% of games here (they score {Math.round(pos.moves[0].score * 100)}%).</p>
              </>
            )}

            <div className="panel-title spaced">Their recurring mistakes</div>
            {profileState === "loading" && <p className="muted small">Checking their games with Stockfish…</p>}
            {profileState === "done" && weaknesses.length === 0 && <p className="muted small">No repeated mistakes found as {color}.</p>}
            <ul className="linelist">
              {weaknesses.map((w, i) => (
                <li key={i} onClick={() => jump([...w.path, w.move], w.opp_color)}>
                  <b>{w.san}?</b> <span className="muted small">−{(w.loss_cp / 100).toFixed(1)} · {w.games} games</span>
                  {w.punish_san && <span className="small"> → punish with <b>{w.punish_san}</b></span>}
                </li>
              ))}
            </ul>

            <div className="panel-title spaced">Their main lines</div>
            <ul className="linelist">
              {mainLines.map((l, i) => (
                <li key={i} onClick={() => jump(l.moves, l.color)}>
                  <span className="small">{l.moves_san.slice(0, 8).join(" ")}…</span>
                  <span className="muted small"> {l.games} games · they score {Math.round(l.score * 100)}%</span>
                </li>
              ))}
              {profileState === "done" && mainLines.length === 0 && <li className="muted small">No line repeated twice.</li>}
            </ul>

            <div className="panel-title spaced">Prepared lines</div>
            {briefingState === "idle" && <button onClick={loadBriefing}>Build extra lines for this opponent</button>}
            {briefingState === "loading" && <p className="muted small">Preparing lines with Stockfish…</p>}
            {briefing && (
              <ul className="linelist">
                {briefing.extra_lines.map((x, i) => (
                  <li key={i} onClick={() => jump(x.moves, x.opponent_color)}>
                    <span className="tag extra">extra line</span>
                    {x.opponent_color && <span className="muted small"> vs their {x.opponent_color === "white" ? "White" : "Black"} · </span>}
                    <span className="small">{x.moves_san.join(" ")}</span>
                    <span className="muted small"> · ends {(x.final_eval_cp / 100).toFixed(2)} for you · ~{x.study_minutes} min</span>
                  </li>
                ))}
                {briefing.novelty?.path && (
                  <li onClick={() => jump([...briefing.novelty.path, briefing.novelty.move], briefing.novelty.opponent_color)}>
                    <span className="tag">surprise</span> <b>{briefing.novelty.san}</b>
                    {briefing.novelty.opponent_color && <span className="muted small"> vs their {briefing.novelty.opponent_color === "white" ? "White" : "Black"}</span>}
                    <span className="muted small"> · engine-sound, rare at master level</span>
                  </li>
                )}
                {briefing.extra_lines.length === 0 && !briefing.novelty && <li className="muted small">No sound extra line found.</li>}
              </ul>
            )}
            <EnginePanel onInfo={setEvaluation} fen={fen} playerColor={you} hideMasters />
          </aside>
        </div>
      )}
    </section>
  );
}
