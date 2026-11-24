import { Chessboard } from "react-chessboard";

// Full-height intro panel for pages that have nothing to show yet (Gap report, Prepare,
// Train, Progress, Deviations). Instead of a lone button above an empty page it explains
// what the page does, offers the action, lists the steps and shows an example position.
export default function PageHero({ title, text, steps = [], fen, arrows = [], orientation = "white", children }) {
  return (
    <div className="page-hero fade-in">
      <div className="ph-copy">
        <h2>{title}</h2>
        <p className="ph-text">{text}</p>
        {children && <div className="ph-actions">{children}</div>}
        {steps.length > 0 && (
          <ol className="ph-steps">
            {steps.map(([t, d], i) => (
              <li key={t}>
                <span className="ph-num">{i + 1}</span>
                <div><b>{t}</b><p>{d}</p></div>
              </li>
            ))}
          </ol>
        )}
      </div>
      {fen && (
        <div className="ph-board" aria-hidden="true">
          <Chessboard position={fen} boardOrientation={orientation} boardWidth={heroBoard()} arePiecesDraggable={false}
            customArrows={arrows} customLightSquareStyle={{ backgroundColor: "var(--board-light)" }}
            customDarkSquareStyle={{ backgroundColor: "var(--board-dark)" }} animationDuration={0} />
        </div>
      )}
    </div>
  );
}

function heroBoard() {
  return Math.max(220, Math.min(380, window.innerWidth - 64));
}
