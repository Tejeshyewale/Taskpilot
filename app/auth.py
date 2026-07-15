"""
Lightweight auth — email/password accounts stored in a local JSON file,
salted+hashed passwords (PBKDF2, stdlib only, no extra dependency),
and bearer session tokens. This is intentionally simple (no JWT, no
external auth provider) — appropriate for a single-machine portfolio
deployment, with the security fundamentals (hashing, salting, no
plaintext passwords, no plaintext tokens reused as identifiers) done
properly rather than skipped.
"""

import os
import json
import hashlib
import secrets
import time

USERS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "users.json")
SESSIONS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "sessions.json")


def _load(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def _save(path: str, data: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()


class AuthError(Exception):
    pass


def signup(email: str, password: str, name: str = "") -> str:
    """Creates a new user. Returns a session token."""
    email = email.strip().lower()
    if not email or "@" not in email:
        raise AuthError("Enter a valid email address.")
    if len(password) < 6:
        raise AuthError("Password must be at least 6 characters.")

    users = _load(USERS_PATH)
    if email in users:
        raise AuthError("An account with this email already exists.")

    salt = secrets.token_hex(16)
    users[email] = {
        "email": email,
        "name": name or email.split("@")[0],
        "salt": salt,
        "password_hash": _hash_password(password, salt),
        "created_at": time.time(),
    }
    _save(USERS_PATH, users)
    return _create_session(email)


def login(email: str, password: str) -> str:
    email = email.strip().lower()
    users = _load(USERS_PATH)
    user = users.get(email)
    if not user or _hash_password(password, user["salt"]) != user["password_hash"]:
        raise AuthError("Incorrect email or password.")
    return _create_session(email)


def _create_session(email: str) -> str:
    sessions = _load(SESSIONS_PATH)
    token = secrets.token_hex(32)
    sessions[token] = {"email": email, "created_at": time.time()}
    _save(SESSIONS_PATH, sessions)
    return token


def get_user_by_token(token: str):
    """Returns the user dict (without password fields) for a valid session token, else None."""
    if not token:
        return None
    sessions = _load(SESSIONS_PATH)
    session = sessions.get(token)
    if not session:
        return None
    users = _load(USERS_PATH)
    user = users.get(session["email"])
    if not user:
        return None
    return {"email": user["email"], "name": user["name"]}


def logout(token: str):
    sessions = _load(SESSIONS_PATH)
    sessions.pop(token, None)
    _save(SESSIONS_PATH, sessions)
