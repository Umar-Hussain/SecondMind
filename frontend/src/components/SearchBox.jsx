import { useEffect, useState } from "react";

// Search input that reports its value after the user pauses typing (250 ms).
export default function SearchBox({ onSearch, placeholder }) {
  const [value, setValue] = useState("");
  useEffect(() => {
    const t = setTimeout(() => onSearch(value.trim()), 250);
    return () => clearTimeout(t);
  }, [value]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="searchbox">
      <span className="search-icon" aria-hidden="true">⌕</span>
      <input type="search" value={value} onChange={(e) => setValue(e.target.value)}
        placeholder={placeholder || "Search by name, opening (Caro-Kann), ECO (B12) or moves (1.e4 c6 2.d4)"} />
      {value && <button className="icon" onClick={() => setValue("")} aria-label="Clear search">✕</button>}
    </div>
  );
}
