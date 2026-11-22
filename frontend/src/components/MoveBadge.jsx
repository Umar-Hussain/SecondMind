// Move quality badge (brilliant !!, great !, best ★, book 📖, inaccuracy ?!, mistake ?, blunder ??),
// coloured like the symbols players know from chess sites. ``a`` is an /annotate result.
export default function MoveBadge({ a, withLabel = false }) {
  if (!a?.kind) return null;
  return (
    <span className={`mq mq-${a.kind}`} title={a.label + (a.loss_cp ? ` (−${(a.loss_cp / 100).toFixed(2)})` : "")}>
      <span className="mq-sym">{a.symbol}</span>
      {withLabel && <span className="mq-label">{a.label}</span>}
    </span>
  );
}

// "+0.35" from a centipawn score (player's point of view).
export function pawns(cp) {
  if (cp == null) return "";
  if (Math.abs(cp) >= 9000) return cp > 0 ? "mate" : "−mate";
  return (cp > 0 ? "+" : cp < 0 ? "−" : "") + (Math.abs(cp) / 100).toFixed(2);
}
