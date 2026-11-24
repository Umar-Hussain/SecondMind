import { Chessboard } from "react-chessboard";

// Small, non-interactive board for cards (like the boards on Lichess's openings page).
// The last move is highlighted in Lichess green.
export default function MiniBoard({ fen, orientation = "white", width = 240, lastMove }) {
  const hl = lastMove
    ? { [lastMove.slice(0, 2)]: { background: "rgba(var(--accent-rgb), .36)" }, [lastMove.slice(2, 4)]: { background: "rgba(var(--accent-rgb), .36)" } }
    : {};
  return (
    <Chessboard
      position={fen}
      boardOrientation={orientation}
      boardWidth={width}
      arePiecesDraggable={false}
      showBoardNotation={false}
      customLightSquareStyle={{ backgroundColor: "var(--board-light)" }}
      customDarkSquareStyle={{ backgroundColor: "var(--board-dark)" }}
      customSquareStyles={hl}
      animationDuration={0}
    />
  );
}
