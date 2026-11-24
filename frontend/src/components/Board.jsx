import { useEffect, useState } from "react";
import { Chessboard } from "react-chessboard";
import { Chess } from "chess.js";
import EvalBar from "./EvalBar.jsx";

// Board colours come from the theme tokens (--board-light / --board-dark).
const LIGHT = { backgroundColor: "var(--board-light)" };
const DARK = { backgroundColor: "var(--board-dark)" };

// Interactive board. Moves are validated client-side with chess.js; the parent
// gets the attempted move. In explore mode the board also keeps its own position
// so the user can try lines without changing the parent state. canDrag(piece) (piece like "wN")
// limits which pieces may be picked up, used by practice mode.
export default function Board({ fen, orientation = "white", arrows = [], onMove, explore = true, width, highlight,
                                evaluation, max = 520, canDrag }) {
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
    ? { [highlight.slice(0, 2)]: { background: "rgba(var(--accent-rgb), .36)" }, [highlight.slice(2, 4)]: { background: "rgba(var(--accent-rgb), .36)" } }
    : {};

  return (
    <div className="board">
      <div className="board-row">
      {showBar && <EvalBar evaluation={evaluation} orientation={orientation} height={width || size} />}
      <Chessboard
        position={position}
        onPieceDrop={onDrop}
        isDraggablePiece={canDrag ? ({ piece }) => canDrag(piece) : undefined}
        boardOrientation={orientation}
        boardWidth={width || size}
        customArrows={arrows}
        customLightSquareStyle={LIGHT}
        customDarkSquareStyle={DARK}
        customSquareStyles={squareStyles}
        customBoardStyle={{ borderRadius: "6px", boxShadow: "var(--shadow-2)" }}
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
