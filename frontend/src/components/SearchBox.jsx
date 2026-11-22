import { useEffect, useState } from "react";

// Lichess-style search field with a blue search button. Reports its value after the
// user pauses typing (250 ms) or presses Enter / the button.
export default function SearchBox({ onSearch, placeholder }) {
  const [value, setValue] = useState("");
  useEffect(() => {
    const t = setTimeout(() => onSearch(value.trim()), 250);
    return () => clearTimeout(t);
  }, [value]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <form className="searchbox" role="search" onSubmit={(e) => { e.preventDefault(); onSearch(value.trim()); }}>
      <input type="search" value={value} onChange={(e) => setValue(e.target.value)} aria-label="Search"
        placeholder={placeholder || "Search by name, opening (Caro-Kann), ECO (B12) or moves (1.e4 c6 2.d4)"} />
      {value && <button type="button" className="icon" onClick={() => setValue("")} aria-label="Clear search">✕</button>}
      <button type="submit" className="search-btn" aria-label="Search">
        <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5" fill="none" stroke="currentColor" strokeWidth="2.4" /><path d="M15.5 15.5 21 21" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" /></svg>
      </button>
    </form>
  );
}
