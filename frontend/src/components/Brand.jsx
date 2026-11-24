// SecondMind wordmark: a knight inside a gold "second" ring (an assistant watching over your games).
// Hover it and the knight hops one L-shaped knight move (the small detail from DESIGN.md).
export default function Brand({ size = 28 }) {
  return (
    <span className="brand">
      <svg className="brand-mark" width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
        <circle cx="16" cy="16" r="14.5" fill="none" stroke="var(--accent)" strokeWidth="2" />
        <circle cx="16" cy="16" r="10.6" fill="none" stroke="var(--accent)" strokeOpacity=".35" strokeWidth="1.2" strokeDasharray="2.6 2.4" />
        <text className="brand-knight" x="16" y="21.6" textAnchor="middle" fontSize="15" fill="var(--text)">♞</text>
      </svg>
      <span className="brand-name">Second<b>Mind</b></span>
    </span>
  );
}
