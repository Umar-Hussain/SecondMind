"""Fill ``objective_eval_cp`` in backend/data/gambits.json with Stockfish.

    python scripts/calibrate_gambits.py [depth]

For every gambit, plays the first theory line to its end and stores the
engine evaluation from White's point of view. The baseline is therefore a
tool-produced fact, never a hand-written number.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import chess  # noqa: E402

from app.tools import engine  # noqa: E402
from app.tools.pgn_utils import san_line_to_uci  # noqa: E402

PATH = ROOT / "backend" / "data" / "gambits.json"


def main(depth: int = 18) -> None:
    data = json.loads(PATH.read_text(encoding="utf-8"))
    for g in data["gambits"]:
        if g["soundness"] == "not_a_real_gambit" or not g["theory_lines"]:
            continue
        board = chess.Board()
        for uci in san_line_to_uci(g["theory_lines"][0]):
            board.push_uci(uci)
        res = engine.evaluate(board.fen(), depth=depth)
        g["objective_eval_cp"] = res.cp_white
        print(f"{g['name']:<28} {res.cp_white:+5d} cp (White) at depth {depth}")
    PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    engine.shutdown()


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 18)
