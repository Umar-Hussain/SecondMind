"""Accounts: password hashing, signed session tokens, roles (user / admin).

* Passwords are stored only as salted PBKDF2-SHA256 hashes (200,000 iterations,
  standard library, constant-time comparison).
* A session token is ``<user_id>.<expiry>.<signature>``, signed with HMAC-SHA256
  using ``SECRET_KEY``. Nothing secret is stored in the browser except the token.
* The admin account is created (or updated) at startup from ``ADMIN_USERNAME`` and
  ``ADMIN_PASSWORD`` in the environment, so no password is ever written in code.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import time
from functools import lru_cache

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import DATA_DIR, get_settings
from app.db import get_session
from app.models import User

PBKDF2_ITERATIONS = 200_000
TOKEN_TTL_SECONDS = 14 * 24 * 3600
USERNAME_RE = re.compile(r"^[a-z0-9_-]{3,32}$")
MIN_PASSWORD = 8


# --- Passwords -------------------------------------------------------------------


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, iters, salt_b64, hash_b64 = stored.split("$")
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt_b64), int(iters))
    return hmac.compare_digest(digest, base64.b64decode(hash_b64))


def validate_new_account(username: str, password: str) -> str:
    """Return the normalized username or raise 422 with a readable reason."""
    name = username.strip().lower()
    if not USERNAME_RE.match(name):
        raise HTTPException(422, "Username: 3-32 characters, letters, digits, '_' or '-'")
    if len(password) < MIN_PASSWORD:
        raise HTTPException(422, f"Password must be at least {MIN_PASSWORD} characters")
    return name


# --- Tokens --------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _secret() -> bytes:
    """SECRET_KEY from the environment, else a random key persisted on first use."""
    configured = get_settings().secret_key
    if configured:
        return configured.encode()
    path = DATA_DIR / "cache" / "secret.key"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(secrets.token_hex(32), encoding="utf-8")
    return path.read_text(encoding="utf-8").strip().encode()


def _sign(payload: str) -> str:
    return hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()


def issue_token(user_id: int, ttl: int = TOKEN_TTL_SECONDS) -> str:
    payload = f"{user_id}.{int(time.time()) + ttl}"
    return f"{payload}.{_sign(payload)}"


def read_token(token: str) -> int | None:
    try:
        uid, exp, sig = token.split(".")
    except ValueError:
        return None
    if not hmac.compare_digest(sig, _sign(f"{uid}.{exp}")) or int(exp) < time.time():
        return None
    return int(uid)


# --- FastAPI dependencies ---------------------------------------------------------------


def current_user(authorization: str | None = Header(default=None),
                 session: Session = Depends(get_session)) -> User:
    """The logged-in user from ``Authorization: Bearer <token>`` (401 otherwise)."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Please log in")
    uid = read_token(authorization.split(" ", 1)[1].strip())
    user = session.get(User, uid) if uid else None
    if user is None:
        raise HTTPException(401, "Session expired, please log in again")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Admins only")
    return user


def public_user(user: User) -> dict:
    return {"id": user.id, "username": user.username, "display_name": user.display_name or user.username,
            "role": user.role, "lichess_username": user.lichess_username,
            "chesscom_username": user.chesscom_username, "rating": user.rating}


# --- Admin bootstrap ------------------------------------------------------------------------


def ensure_admin(session: Session) -> User | None:
    """Create or update the admin from ADMIN_USERNAME / ADMIN_PASSWORD (no-op if either is unset)."""
    s = get_settings()
    if not (s.admin_username and s.admin_password):
        return None
    name = s.admin_username.strip().lower()
    user = session.scalars(select(User).where(User.username == name)).first()
    if user is None:
        user = User(username=name, display_name=s.admin_username.strip())
        session.add(user)
    user.role = "admin"
    if not verify_password(s.admin_password, user.password_hash):
        user.password_hash = hash_password(s.admin_password)
    session.commit()
    return user
