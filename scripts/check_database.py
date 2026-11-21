"""Smoke-test SecondMind against a real database (e.g. Neon) and clean up afterwards.

    python scripts/check_database.py            # uses NEON_DATABASE_URL from .env

Creates the tables if needed, then runs the account and library flow through the
real API (sign up, log in, admin publish, copy, edit, delete) with throwaway
accounts, and deletes everything it created. Prints PASS/FAIL per step.
"""

from __future__ import annotations

import os
import re
import secrets
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def env_value(name: str) -> str:
    text = (ROOT / ".env").read_text(encoding="utf-8") if (ROOT / ".env").exists() else ""
    m = re.search(rf"(?m)^{name}=(.*)$", text)
    return (m.group(1).strip() if m else "") or os.environ.get(name, "")


url = env_value("NEON_DATABASE_URL") or env_value("DATABASE_URL")
if not url.startswith(("postgres://", "postgresql://")):
    sys.exit("No Postgres URL found (set NEON_DATABASE_URL in .env)")
os.environ["DATABASE_URL"] = url
os.environ["OFFLINE"] = "1"
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import inspect, select  # noqa: E402

from app.db import SessionLocal, engine, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Repertoire, User  # noqa: E402
from app.auth import hash_password  # noqa: E402
from app.tools.repertoire import delete_repertoire  # noqa: E402

# A variation must follow the move it replaces: ( 3. Nc3 ... ) comes right after 3. e5.
PGN = '[Event "x"]\n\n1. e4 c6 2. d4 d5 3. e5 ( 3. Nc3 dxe4 4. Nxe4 Bf5 ) 3... Bf5 4. Nf3 e6 *'
results: list[tuple[str, bool, str]] = []


def step(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  - ' + detail) if detail else ''}", flush=True)


tag = secrets.token_hex(3)
user_name, admin_name = f"zz_check_user_{tag}", f"zz_check_admin_{tag}"
password = secrets.token_urlsafe(12)
start = time.perf_counter()
try:
    print(f"Database dialect: {engine.dialect.name}")
    init_db()
    tables = set(inspect(engine).get_table_names())
    step("tables created", {"users", "repertoires", "repertoire_nodes", "games"} <= tables, f"{len(tables)} tables")

    with SessionLocal() as s:  # throwaway admin, created directly
        s.add(User(username=admin_name, password_hash=hash_password(password), role="admin"))
        s.commit()

    with TestClient(app) as api:
        r = api.post("/auth/signup", json={"username": user_name, "password": password})
        step("sign up", r.status_code == 200, str(r.status_code))
        user_h = {"Authorization": f"Bearer {r.json()['token']}"}
        r = api.post("/auth/login", json={"username": user_name, "password": password})
        step("log in", r.status_code == 200)
        r = api.post("/auth/login", json={"username": admin_name, "password": password})
        admin_h = {"Authorization": f"Bearer {r.json()['token']}"}

        r = api.post("/library", headers=admin_h, json={"name": f"Caro check {tag}", "color": "black", "pgn": PGN,
                                                         "description": "database check"})
        lib_id = r.json().get("id")
        step("admin publishes to library", bool(r.json().get("saved")), f"id {lib_id}")
        step("user cannot publish", api.post("/library", headers=user_h, json={"name": "x", "color": "white",
                                                                               "moves_text": "1.e4"}).status_code == 403)
        listing = api.get("/library", headers=user_h).json()
        step("user sees the library", any(x["id"] == lib_id for x in listing))
        r = api.get("/library", headers=user_h, params={"q": "caro"})
        if r.status_code == 200:
            step("library search", any(x["id"] == lib_id for x in r.json()))
        copy = api.post(f"/library/{lib_id}/copy", headers=user_h, json={}).json()
        step("add to my repertoires", lib_id is not None and copy.get("copied_from_id") == lib_id)
        tree = api.get(f"/repertoires/{copy['id']}/tree", headers=user_h).json()
        step("copied tree readable", len(tree.get("nodes", [])) > 5, f"{len(tree.get('nodes', []))} positions")
        root = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"
        r = api.patch(f"/repertoires/{copy['id']}/nodes", headers=user_h, json={"fen_key": root,
                                                                                "add_opponent_move": "d2d4"})
        step("edit own copy", r.status_code == 200)
        r = api.post(f"/repertoires/{copy['id']}/remove-move", headers=user_h, json={"fen_key": root, "move": "d2d4"})
        step("prune own copy", r.status_code == 200)
    step("total time", True, f"{time.perf_counter() - start:.1f}s")
finally:
    # Clean up everything this script created.
    with SessionLocal() as s:
        # Every throwaway account, including leftovers from an earlier interrupted run.
        for u in s.scalars(select(User).where(User.username.like("zz_check_%"))).all():
            for rep in s.scalars(select(Repertoire).where(Repertoire.user_id == u.id)).all():
                delete_repertoire(s, rep.id)
            s.delete(u)
            s.commit()
            print(f"deleted throwaway account {u.username}")
    print("cleanup done: throwaway accounts and repertoires deleted")

failed = [n for n, ok, _ in results if not ok]
print("ALL PASS" if not failed else f"FAILED: {failed}")
sys.exit(1 if failed else 0)
