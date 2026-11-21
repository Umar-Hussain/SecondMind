"""Download the full Lichess chess-openings ECO tables (CC0 licensed).

    python scripts/download_eco.py

Saves a.tsv .. e.tsv into backend/data/eco/. Without them the classifier uses
the smaller bundled.tsv subset shipped with the repository.
Source: https://github.com/lichess-org/chess-openings (public domain / CC0).
"""

from pathlib import Path

import httpx

BASE = "https://raw.githubusercontent.com/lichess-org/chess-openings/master/{}.tsv"
OUT = Path(__file__).resolve().parents[1] / "backend" / "data" / "eco"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for letter in "abcde":
        resp = httpx.get(BASE.format(letter), timeout=60)
        resp.raise_for_status()
        (OUT / f"{letter}.tsv").write_text(resp.text, encoding="utf-8")
        print(f"saved {letter}.tsv ({len(resp.text.splitlines())} lines)")


if __name__ == "__main__":
    main()
