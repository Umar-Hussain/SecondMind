// Opening tree of one opponent's games, built in the browser (same idea as Scout's explorer).
//
// Positions are keyed by the normalized FEN (first four fields), so transpositions merge.
// Each game is counted at most once per position. Results are from the OPPONENT's point
// of view: game rows carry `opp_color` and `result` ("win" | "draw" | "loss" for them).
import { Chess } from "chess.js";
import { fenKey } from "../api.js";

export function buildTree(games, { color = "white", speed = "all" } = {}) {
  const index = new Map(); // key -> { games: [], moves: Map(uci -> stat) }
  const get = (key) => {
    let node = index.get(key);
    if (!node) {
      node = { games: [], moves: new Map() };
      index.set(key, node);
    }
    return node;
  };

  const used = games.filter((g) => g.opp_color === color && (speed === "all" || g.speed === speed));
  for (const g of used) {
    const board = new Chess();
    const seen = new Set();
    for (let i = 0; i <= g.moves.length; i++) {
      const key = fenKey(board.fen());
      if (seen.has(key)) break; // a repeated position: stop counting this game further
      seen.add(key);
      const node = get(key);
      node.games.push(g);
      const uci = g.moves[i];
      if (!uci) break;
      let move;
      try {
        move = board.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] });
      } catch {
        break; // corrupt game: keep what was counted so far
      }
      let stat = node.moves.get(uci);
      if (!stat) {
        stat = { uci, san: move.san, from: move.from, to: move.to, games: [], win: 0, draw: 0, loss: 0 };
        node.moves.set(uci, stat);
      }
      stat.games.push(g);
      stat[g.result] += 1;
    }
  }
  return { index, total: used.length };
}

// Stats for one position: candidate moves sorted by popularity, with the opponent's score.
export function positionData(tree, fen) {
  const node = tree.index.get(fenKey(fen));
  const total = node ? node.games.length : 0;
  const moves = node
    ? [...node.moves.values()].map((m) => {
        const n = m.games.length;
        return {
          ...m,
          count: n,
          share: total ? m.games.length / total : 0,
          score: (m.win + 0.5 * m.draw) / n, // the opponent's score after this move
        };
      })
    : [];
  moves.sort((a, b) => b.count - a.count);
  return { total, moves, games: node ? node.games : [] };
}

// Colour of an arrow by the opponent's score: red = they do well, green = they do badly.
export function scoreColor(score, alpha = 0.85) {
  if (score >= 0.6) return `rgba(204,51,51,${alpha})`;
  if (score <= 0.4) return `rgba(98,153,36,${alpha})`;
  return `rgba(213,144,32,${alpha})`;
}
