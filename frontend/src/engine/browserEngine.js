// Stockfish running in the visitor's browser (WebAssembly in a Web Worker).
//
// The live analysis panel uses this instead of the server, so free hosting only
// has to run the batch analysis and the verification guard. The single-threaded
// "lite" build needs no special COOP/COEP headers and works on any host.
import { Chess } from "chess.js";

const WORKER_URL = "/stockfish/stockfish-19-lite-single.js";
const MATE = 10000;

export function browserEngineSupported() {
  return typeof Worker !== "undefined" && typeof WebAssembly === "object";
}

// Parse one UCI "info" line into {depth, multipv, cpStm, mate, pv[]}.
function parseInfo(line) {
  const t = line.split(" ");
  const get = (k) => {
    const i = t.indexOf(k);
    return i >= 0 ? t[i + 1] : undefined;
  };
  const pvAt = t.indexOf("pv");
  if (pvAt < 0 || !get("depth") || !get("score")) return null;
  const scoreType = get("score"); // "cp" or "mate"
  const value = Number(t[t.indexOf("score") + 2]);
  return {
    depth: Number(get("depth")),
    multipv: Number(get("multipv") || 1),
    cpStm: scoreType === "mate" ? (value > 0 ? MATE - value : -MATE - value) : value,
    mate: scoreType === "mate" ? value : null,
    pv: t.slice(pvAt + 1),
  };
}

function pvToSan(fen, pv) {
  const game = new Chess(fen);
  const out = [];
  for (const uci of pv.slice(0, 10)) {
    try {
      const m = game.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] });
      out.push(m.san);
    } catch {
      break;
    }
  }
  return out;
}

// Creates an engine; analyse(fen, onUpdate) streams updates in the same shape as the
// server WebSocket ({depth, cp_white, mate, lines:[{move, san_pv, cp_white, mate}]}).
export function createBrowserEngine({ multipv = 3, maxDepth = 22, minIntervalMs = 250 } = {}) {
  const worker = new Worker(WORKER_URL);
  let current = null; // {fen, onUpdate, lines, lastSent}
  let ready = false;
  const queue = [];

  const send = (cmd) => (ready ? worker.postMessage(cmd) : queue.push(cmd));

  worker.onmessage = (e) => {
    const line = typeof e.data === "string" ? e.data : "";
    if (line === "uciok") {
      worker.postMessage(`setoption name MultiPV value ${multipv}`);
      worker.postMessage("isready");
      return;
    }
    if (line === "readyok" && !ready) {
      ready = true;
      queue.splice(0).forEach((c) => worker.postMessage(c));
      return;
    }
    if (!current || !line.startsWith("info") || !line.includes(" pv ")) return;
    const info = parseInfo(line);
    if (!info) return;
    const whiteToMove = current.fen.split(" ")[1] === "w";
    const sign = whiteToMove ? 1 : -1;
    current.lines[info.multipv - 1] = {
      move: info.pv[0],
      san_pv: pvToSan(current.fen, info.pv),
      cp_white: sign * info.cpStm,
      mate: info.mate == null ? null : sign * info.mate,
      depth: info.depth,
    };
    const lines = current.lines.filter(Boolean);
    const now = performance.now();
    if (lines.length && now - current.lastSent >= minIntervalMs) {
      current.lastSent = now;
      current.onUpdate({ depth: info.depth, cp_white: lines[0].cp_white, mate: lines[0].mate, lines });
    }
  };
  worker.postMessage("uci");

  return {
    analyse(fen, onUpdate) {
      send("stop"); // a new position cancels the previous search
      current = { fen, onUpdate, lines: [], lastSent: 0 };
      send("ucinewgame");
      send(`position fen ${fen}`);
      send(`go depth ${maxDepth}`);
    },
    stop() {
      send("stop");
      current = null;
    },
    terminate() {
      worker.terminate();
    },
  };
}
