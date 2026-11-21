// SecondMind wordmark: a knight inside a "second" ring (an assistant watching over your games).
export default function Brand({ size = 28 }) {
  return (
    <span className="brand">
      <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
        <circle cx="16" cy="16" r="14.5" fill="none" stroke="var(--primary)" strokeWidth="2.2" />
        <circle cx="16" cy="16" r="10.5" fill="none" stroke="var(--good)" strokeWidth="1.4" strokeDasharray="3 2.2" />
        <text x="16" y="21.5" textAnchor="middle" fontSize="15" fill="var(--text-strong)">♞</text>
      </svg>
      <span className="brand-name">Second<b>Mind</b></span>
    </span>
  );
}
