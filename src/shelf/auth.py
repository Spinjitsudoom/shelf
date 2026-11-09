"""Accounts: people who can sign in, their passwords, and the signed session they get.

Each person has their own Favourites, playlists and listening history. Admins also manage
the server: accounts, music folders, rescans and the cache.

A session is a signed token carrying the user's id and their "session version". Changing a
password or removing an account bumps the version, which signs that person out everywhere.
The token travels as a cookie (the web app) or an `Authorization: Bearer` header.

The first account: if there are no accounts yet and config.toml has a `password`, an admin
called "admin" is made with it. Otherwise the app asks whoever opens it first to make one.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

from itsdangerous import BadSignature, TimestampSigner

from .db import session

COOKIE = "shelf_session"
MAX_AGE = 60 * 60 * 24 * 365
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,31}$")
MIN_PASSWORD = 6
LOCK_AFTER = 8  # wrong passwords from one address...
LOCK_WINDOW = 15 * 60  # ...within this many seconds lock it out for the rest of the window


@dataclass(frozen=True)
class User:
    id: int
    username: str
    admin: bool
    version: int

    def json(self) -> dict:
        return {"id": self.id, "username": self.username, "admin": self.admin}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        kind, salt, digest = stored.split("$")
    except ValueError:
        return False
    if kind != "scrypt":
        return False
    got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1, dklen=32)
    return hmac.compare_digest(got.hex(), digest)


def check_username(name: str) -> str:
    name = re.sub(r"\s+", " ", name or "").strip()
    if not NAME_RE.match(name):
        raise ValueError("Use 1–32 letters, numbers, spaces, dots, dashes or underscores, starting with a letter or number")
    return name


def check_password_rules(password: str) -> None:
    if len(password or "") < MIN_PASSWORD:
        raise ValueError(f"Use at least {MIN_PASSWORD} characters")
    if len(password) > 256:
        raise ValueError("That password is too long")


class Auth:
    def __init__(self, db_path: Path, secret_key: str, seed_password: str = ""):
        self.db_path = db_path
        self.signer = TimestampSigner(secret_key, salt="shelf-session")
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._cache: dict[int, User | None] = {}
        self._lock = threading.Lock()
        self._seen: dict[int, float] = {}
        if seed_password and not self.has_users():
            self.create("admin", seed_password, admin=True, check=False)

    # ---------- accounts ----------

    def has_users(self) -> bool:
        with session(self.db_path) as conn:
            return conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None

    def create(self, username: str, password: str, admin: bool = False, check: bool = True) -> User:
        username = check_username(username)
        if check:
            check_password_rules(password)
        with session(self.db_path) as conn:
            try:
                uid = conn.execute(
                    "INSERT INTO users(username, pw_hash, is_admin, created_at) VALUES(?, ?, ?, ?)",
                    (username, hash_password(password), int(admin), time.time()),
                ).lastrowid
            except sqlite3.IntegrityError as e:
                raise ValueError(f"There’s already an account called {username}") from e
        self.forget(uid)
        return self.get(uid)

    def get(self, uid: int) -> User | None:
        with self._lock:
            if uid in self._cache:
                return self._cache[uid]
        with session(self.db_path) as conn:
            r = conn.execute("SELECT id, username, is_admin, session_ver FROM users WHERE id = ?", (uid,)).fetchone()
        user = User(r["id"], r["username"], bool(r["is_admin"]), r["session_ver"]) if r else None
        with self._lock:
            self._cache[uid] = user
        return user

    def forget(self, uid: int) -> None:
        with self._lock:
            self._cache.pop(uid, None)

    def find(self, username: str) -> sqlite3.Row | None:
        with session(self.db_path) as conn:
            return conn.execute("SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username.strip(),)).fetchone()

    def set_password(self, uid: int, password: str) -> None:
        """New password; signs the person out on every device."""
        check_password_rules(password)
        with session(self.db_path) as conn:
            conn.execute("UPDATE users SET pw_hash = ?, session_ver = session_ver + 1 WHERE id = ?",
                         (hash_password(password), uid))
        self.forget(uid)

    def sign_out_everywhere(self, uid: int) -> None:
        with session(self.db_path) as conn:
            conn.execute("UPDATE users SET session_ver = session_ver + 1 WHERE id = ?", (uid,))
        self.forget(uid)

    def admins(self) -> int:
        with session(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1").fetchone()[0]

    # ---------- sessions ----------

    def make_token(self, user: User) -> str:
        return self.signer.sign(f"{user.id}.{user.version}".encode()).decode()

    def user_for(self, token: str | None) -> User | None:
        if not token:
            return None
        try:
            raw = self.signer.unsign(token, max_age=MAX_AGE).decode()
            uid, ver = (int(x) for x in raw.split("."))
        except (BadSignature, ValueError):
            return None
        user = self.get(uid)
        if not user or user.version != ver:
            return None
        self._seen[uid] = time.time()
        return user

    def last_seen(self, uid: int) -> float | None:
        return self._seen.get(uid)

    def flush_seen(self) -> None:
        """Store when people were last active (kept in memory between flushes)."""
        seen = dict(self._seen)
        if not seen:
            return
        with session(self.db_path) as conn:
            conn.executemany("UPDATE users SET last_seen = MAX(COALESCE(last_seen, 0), ?) WHERE id = ?",
                             [(t, uid) for uid, t in seen.items()])

    # ---------- sign-in attempts ----------

    def locked_out(self, client: str) -> bool:
        window = self._failures[client]
        cutoff = time.time() - LOCK_WINDOW
        while window and window[0] < cutoff:
            window.popleft()
        return len(window) >= LOCK_AFTER

    def failures(self) -> list[dict]:
        """Addresses with wrong passwords in the last 15 minutes, for the admin dashboard."""
        now = time.time()
        out = []
        for client in list(self._failures):
            window = self._failures[client]
            while window and window[0] < now - LOCK_WINDOW:
                window.popleft()
            if not window:
                self._failures.pop(client, None)
                continue
            locked = len(window) >= LOCK_AFTER
            out.append({"address": client, "attempts": len(window), "locked": locked,
                        "until": window[-LOCK_AFTER] + LOCK_WINDOW if locked else None, "last": window[-1]})
        return sorted(out, key=lambda x: -x["last"])

    def clear_failures(self, client: str | None = None) -> int:
        """Forget wrong passwords (for one address, or all), lifting any lockout."""
        if client is None:
            n = len(self._failures)
            self._failures.clear()
            return n
        return 1 if self._failures.pop(client, None) is not None else 0

    def attempt(self, client: str, username: str, password: str) -> User | None:
        row = self.find(username) if username else None
        ok = verify_password(password, row["pw_hash"]) if row else verify_password(password, _DUMMY)
        if ok:
            self._failures.pop(client, None)
            return self.get(row["id"])
        self._failures[client].append(time.time())
        return None


_DUMMY = hash_password(secrets.token_hex(8))  # so unknown names take as long as wrong passwords


def token_from(headers, cookies) -> str | None:
    """The session token from an `Authorization: Bearer` header, else the cookie."""
    auth = headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return cookies.get(COOKIE)
