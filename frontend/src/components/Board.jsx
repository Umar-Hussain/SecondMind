import { useEffect, useState } from "react";
import { Chessboard } from "react-chessboard";
import { Chess } from "chess.js";

// Interactive board. Moves are validated client-side with chess.js; the parent
// gets the new FEN (explore mode) or the attempted move (quiz mode).
export default function Board({ fen, orientation = "white", arrows = [], onMove, explore = true, width = 420 }) {
  const [position, setPosition] = useState(fen);

  useEffect(() => setPosition(fen), [fen]);

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
    onMove && onMove({ uci: move.from + move.to + (move.promotion || ""), san: move.san, fen: game.fen() });
    return true;
  }

  return (
    <div className="board">
      <Chessboard
        position={position}
        onPieceDrop={onDrop}
        boardOrientation={orientation}
        boardWidth={width}
        customArrows={arrows}
        animationDuration={150}
      />
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
