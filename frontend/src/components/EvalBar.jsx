// Vertical evaluation bar beside the board (Lichess style).
// The white share follows Lichess's winning-chances curve, so +0.3 barely moves it and
// +5 fills most of it; a mate fills it completely. It flips with the board.
export function whiteShare(evaluation) {
  if (!evaluation) return 50;
  if (evaluation.mate != null) return evaluation.mate > 0 ? 100 : 0;
  const cp = Math.max(-1500, Math.min(1500, evaluation.cp_white ?? 0));
  const chances = 2 / (1 + Math.exp(-0.00368208 * cp)) - 1; // -1 .. 1
  return 50 + 50 * chances;
}

export function evalLabel(evaluation) {
  if (!evaluation) return "";
  if (evaluation.mate != null) return `M${Math.abs(evaluation.mate)}`;
  const v = (evaluation.cp_white ?? 0) / 100;
  return `${v > 0 ? "+" : ""}${v.toFixed(1)}`;
}

export default function EvalBar({ evaluation, orientation = "white", height }) {
  const white = whiteShare(evaluation);
  const whiteAhead = evaluation ? (evaluation.mate != null ? evaluation.mate > 0 : (evaluation.cp_white ?? 0) >= 0) : true;
  const flipped = orientation === "black";
  // The label sits at the end of the side that is better.
  const labelAtBottom = whiteAhead !== flipped;
  return (
    <div className={`board-evalbar ${flipped ? "flipped" : ""}`} style={{ height }}
      role="img" aria-label={evaluation ? `Evaluation ${evalLabel(evaluation)} for White` : "Evaluation pending"}>
      <div className="board-evalbar-white" style={{ height: `${white}%` }} />
      {evaluation && (
        <span className={`board-evalbar-label ${labelAtBottom ? "bottom" : "top"} ${whiteAhead ? "on-white" : "on-black"}`}>
          {evalLabel(evaluation)}
        </span>
      )}
    </div>
  );
}
