"""Start the backend for local development.

    python scripts/dev_backend.py            # demo mode: OFFLINE=1, fixture data
    python scripts/dev_backend.py --live     # real Lichess / Chess.com calls

Demo mode uses the synthetic fixture accounts ``demo_player`` (Lichess),
``demo_player_cc`` (Chess.com) and the opponent ``rival_player``.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if "--live" not in sys.argv:
    os.environ.setdefault("OFFLINE", "1")
sys.path.insert(0, str(ROOT / "backend"))

import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=int(os.environ.get("PORT", 8000)),
                app_dir=str(ROOT / "backend"))
