import { useEffect, useState } from "react";
import { Chessboard } from "react-chessboard";
import { Chess } from "chess.js";
import EvalBar from "./EvalBar.jsx";

// Lichess "brown" board colours.
const LIGHT = { backgroundColor: "#f0d9b5" };
const DARK = { backgroundColor: "#b58863" };

// Interactive board. Moves are validated client-side with chess.js; the parent
// gets the attempted move. In explore mode the board also keeps its own position
// so the user can try lines without changing the parent state.
export default function Board({ fen, orientation = "white", arrows = [], onMove, explore = true, width, highlight,
                                evaluation, max = 520 }) {
  const showBar = evaluation !== undefined; // pass null while the engine is still thinking
  const [position, setPosition] = useState(fen);
  const [size, setSize] = useState(width || 440);

  useEffect(() => setPosition(fen), [fen]);
  useEffect(() => {
    if (width) return undefined;
    const fit = () => setSize(Math.max(260, Math.min(max, window.innerWidth - (showBar ? 70 : 40), window.innerHeight - 120)));
    fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, [width, max]);

  function onDrop(from, to, piece) {
    const game = new Chess(position);
    let move = null;
    try {
      const promotion = piece && piece[1] === "P" && (to[1] === "8" || to[1] === "1") ? "q" : undefined;
      move = game.move({ from, to, promotion });
    } catch {
      return false; // illegal move: chess.js throws, the piece snaps back
    }
    if (explore) setPosition(game.fen());
    onMove && onMove({ uci: move.from + move.to + (move.promotion || ""), san: move.san, fen: game.fen(), from: position });
    return true;
  }

  const squareStyles = highlight
    ? { [highlight.slice(0, 2)]: { background: "rgba(155,199,0,.41)" }, [highlight.slice(2, 4)]: { background: "rgba(155,199,0,.41)" } }
    : {};

  return (
    <div className="board">
      <div className="board-row">
      {showBar && <EvalBar evaluation={evaluation} orientation={orientation} height={size} />}
      <Chessboard
        position={position}
        onPieceDrop={onDrop}
        boardOrientation={orientation}
        boardWidth={size}
        customArrows={arrows}
        customLightSquareStyle={LIGHT}
        customDarkSquareStyle={DARK}
        customSquareStyles={squareStyles}
        customBoardStyle={{ borderRadius: "3px", boxShadow: "0 2px 12px rgba(0,0,0,.45)" }}
        animationDuration={150}
      />
      </div>
      {explore && position !== fen && (
        <button className="link" onClick={() => { setPosition(fen); onMove && onMove({ reset: true, fen }); }}>
          ↺ back to the position
        </button>
      )}
    </div>
  );
}

// "e2e4" -> ["e2", "e4", color] for react-chessboard arrows.
export function arrow(uci, color) {
  return uci ? [uci.slice(0, 2), uci.slice(2, 4), color] : null;
}
