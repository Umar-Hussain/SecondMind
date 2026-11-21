"""Accounts, permissions, the admin-published library, and repertoire editing."""

import chess
import pytest
from fastapi.testclient import TestClient

from app import auth
from app.config import FIXTURES_DIR, get_settings
from app.db import SessionLocal, init_db
from app.main import app
from app.tools.pgn_utils import fen_key, san_line_to_uci

WHITE_PGN = (FIXTURES_DIR / "repertoire_white.pgn").read_text()


def key_after(moves: str) -> str:
    b = chess.Board()
    for u in san_line_to_uci(moves):
        b.push_uci(u)
    return fen_key(b)


@pytest.fixture(scope="module")
def api():
    with TestClient(app) as c:
        yield c


def _signup(api, name: str) -> dict:
    res = api.post("/auth/signup", json={"username": name, "password": "a-long-password"})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


@pytest.fixture(scope="module")
def admin_headers(api) -> dict:
    s = get_settings()
    s.admin_username, s.admin_password = "TestAdmin", "admin-password-123"
    try:
        init_db()
        with SessionLocal() as session:
            assert auth.ensure_admin(session).role == "admin"
    finally:
        s.admin_username, s.admin_password = "", ""
    tok = api.post("/auth/login", json={"username": "testadmin", "password": "admin-password-123"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


# --- Accounts -------------------------------------------------------------------


def test_password_hashing() -> None:
    h = auth.hash_password("s3cret-pass")
    assert h.startswith("pbkdf2_sha256$") and "s3cret-pass" not in h
    assert auth.verify_password("s3cret-pass", h) and not auth.verify_password("wrong", h)


def test_token_round_trip_and_tamper() -> None:
    tok = auth.issue_token(42)
    assert auth.read_token(tok) == 42
    uid, exp, sig = tok.split(".")
    assert auth.read_token(f"43.{exp}.{sig}") is None  # tampered user id
    assert auth.read_token(auth.issue_token(42, ttl=-1)) is None  # expired


def test_signup_login_me(api) -> None:
    h = _signup(api, "Magnus_Fan")
    me = api.get("/auth/me", headers=h).json()
    assert me["username"] == "magnus_fan" and me["role"] == "user"
    assert api.post("/auth/signup", json={"username": "magnus_fan", "password": "another-pass"}).status_code == 409
    assert api.post("/auth/login", json={"username": "MAGNUS_FAN", "password": "a-long-password"}).status_code == 200
    assert api.post("/auth/login", json={"username": "magnus_fan", "password": "nope-nope"}).status_code == 401
    upd = api.patch("/auth/me", headers=h, json={"lichess_username": "demo_player", "rating": 1700}).json()
    assert upd["lichess_username"] == "demo_player" and upd["rating"] == 1700


def test_validation_and_auth_required(api) -> None:
    assert api.post("/auth/signup", json={"username": "x", "password": "long-enough"}).status_code == 422
    assert api.post("/auth/signup", json={"username": "okname", "password": "short"}).status_code == 422
    assert api.get("/repertoires").status_code == 401
    assert api.get("/repertoires", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_users_cannot_see_each_others_repertoires(api) -> None:
    alice, bob = _signup(api, "alice_x"), _signup(api, "bob_x")
    rep = api.post("/repertoires", headers=alice, json={"name": "mine", "color": "white", "pgn": WHITE_PGN}).json()
    assert api.get(f"/repertoires/{rep['id']}/tree", headers=bob).status_code == 404
    assert api.delete(f"/repertoires/{rep['id']}", headers=bob).status_code == 404
    assert [r["id"] for r in api.get("/repertoires", headers=bob).json()] == []


# --- Library ---------------------------------------------------------------------


def test_only_admins_publish(api, admin_headers) -> None:
    user = _signup(api, "carol_x")
    body = {"name": "Ruy Lopez for beginners", "color": "white", "pgn": WHITE_PGN, "description": "Solid 1.e4"}
    assert api.post("/library", headers=user, json=body).status_code == 403
    res = api.post("/library", headers=admin_headers, json=body).json()
    assert res["saved"]


def test_library_view_copy_and_edit(api, admin_headers) -> None:
    lib = api.post("/library", headers=admin_headers,
                   json={"name": "Caro-Kann starter", "color": "black",
                         "pgn": (FIXTURES_DIR / "repertoire_black.pgn").read_text()}).json()
    user = _signup(api, "dave_x")

    listing = api.get("/library", headers=user).json()
    item = next(r for r in listing if r["id"] == lib["id"])
    assert item["is_library"] and not item["in_my_repertoires"]
    tree = api.get(f"/repertoires/{lib['id']}/tree", headers=user).json()  # users can view the library tree
    assert tree["is_library"] and len(tree["nodes"]) > 5

    # Library repertoires are read-only for users...
    assert api.post(f"/repertoires/{lib['id']}/remove-move", headers=user,
                    json={"fen_key": key_after("e4 c6"), "move": "d7d5"}).status_code == 403

    # ...but they can add a copy to their own repertoires and change it.
    copy = api.post(f"/library/{lib['id']}/copy", headers=user, json={"name": "My Caro"}).json()
    assert copy["copied_from_id"] == lib["id"] and not copy["is_library"]
    assert next(r for r in api.get("/library", headers=user).json() if r["id"] == lib["id"])["in_my_repertoires"]

    # Add a reply to 2.Nf3 (not covered), then remove the 1.d4 branch entirely.
    assert api.patch(f"/repertoires/{copy['id']}/nodes", headers=user,
                     json={"fen_key": key_after("e4 c6"), "add_opponent_move": "g1f3"}).status_code == 200
    assert api.patch(f"/repertoires/{copy['id']}/nodes", headers=user,
                     json={"fen_key": key_after("e4 c6 Nf3"), "user_move": "d7d5"}).status_code == 200
    before = len(api.get(f"/repertoires/{copy['id']}/tree", headers=user).json()["nodes"])
    removed = api.post(f"/repertoires/{copy['id']}/remove-move", headers=user,
                       json={"fen_key": key_after(""), "move": "d2d4"}).json()["removed_positions"]
    after = api.get(f"/repertoires/{copy['id']}/tree", headers=user).json()
    assert removed >= 3 and len(after["nodes"]) == before - removed
    # The library original is untouched.
    original = api.get(f"/repertoires/{lib['id']}/tree", headers=user).json()
    assert any(n["fen_key"] == key_after("d4") for n in original["nodes"])

    # Illegal edits are rejected.
    assert api.patch(f"/repertoires/{copy['id']}/nodes", headers=user,
                     json={"fen_key": key_after("e4 c6"), "add_opponent_move": "e1e8"}).status_code == 422


def test_admin_bootstrap_is_idempotent(admin_headers) -> None:
    s = get_settings()
    s.admin_username, s.admin_password = "TestAdmin", "admin-password-123"
    try:
        with SessionLocal() as session:
            first = auth.ensure_admin(session)
            again = auth.ensure_admin(session)
            assert first.id == again.id
    finally:
        s.admin_username, s.admin_password = "", ""


# --- Search ----------------------------------------------------------------------


def test_library_search(api, admin_headers) -> None:
    white = api.post("/library", headers=admin_headers,
                     json={"name": "Search test white", "color": "white", "pgn": WHITE_PGN,
                           "description": "solid e4 starter"}).json()["id"]
    black = api.post("/library", headers=admin_headers,
                     json={"name": "Search test black", "color": "black",
                           "pgn": (FIXTURES_DIR / "repertoire_black.pgn").read_text()}).json()["id"]
    user = _signup(api, "erin_x")

    def ids(q: str) -> set[int]:
        return {r["id"] for r in api.get("/library", headers=user, params={"q": q}).json()} & {white, black}

    assert ids("") == {white, black}
    assert ids("solid starter") == {white}                 # words in the description
    assert ids("caro advance") == {black, white}           # opening names inside both trees
    assert ids("najdorf") == set()                         # neither repertoire reaches the Najdorf
    assert ids("B12") == {black, white}                    # ECO code
    assert ids("1.e4 c6 2.d4 d5 3.e5") == {black, white}   # a move sequence both contain
    assert ids("e4 c6 Nc3 d5 d4") == {black}               # transposition into the black tree
    assert ids("1.e4 d5") == set()                         # Scandinavian: in neither
    res = api.get("/library", headers=user, params={"q": "e4 e5 Nf3"}).json()
    hit = next(r for r in res if r["id"] == white)
    assert hit["match"] == "contains e4 e5 Nf3"


def test_my_repertoires_search(api) -> None:
    user = _signup(api, "frank_x")
    api.post("/repertoires", headers=user, json={"name": "Ruy main", "color": "white", "pgn": WHITE_PGN})
    assert len(api.get("/repertoires", headers=user, params={"q": "ruy"}).json()) == 1
    assert api.get("/repertoires", headers=user, params={"q": "dutch"}).json() == []


# --- Passwords ----------------------------------------------------------------------


def test_change_password(api) -> None:
    h = _signup(api, "gina_x")
    assert api.post("/auth/password", headers=h, json={"current_password": "wrong-one",
                                                       "new_password": "brand-new-pass"}).status_code == 403
    assert api.post("/auth/password", headers=h, json={"current_password": "a-long-password",
                                                       "new_password": "short"}).status_code == 422
    assert api.post("/auth/password", headers=h, json={"current_password": "a-long-password",
                                                       "new_password": "brand-new-pass"}).status_code == 200
    assert api.post("/auth/login", json={"username": "gina_x", "password": "a-long-password"}).status_code == 401
    assert api.post("/auth/login", json={"username": "gina_x", "password": "brand-new-pass"}).status_code == 200


def test_admin_user_list_and_reset(api, admin_headers) -> None:
    user = _signup(api, "hank_x")
    assert api.get("/admin/users", headers=user).status_code == 403
    users = api.get("/admin/users", headers=admin_headers).json()
    hank = next(u for u in users if u["username"] == "hank_x")
    assert "password_hash" not in hank and hank["role"] == "user"
    assert api.post(f"/admin/users/{hank['id']}/password", headers=user,
                    json={"new_password": "temp-pass-123"}).status_code == 403
    assert api.post(f"/admin/users/{hank['id']}/password", headers=admin_headers,
                    json={"new_password": "temp-pass-123"}).status_code == 200
    assert api.post("/auth/login", json={"username": "hank_x", "password": "temp-pass-123"}).status_code == 200
