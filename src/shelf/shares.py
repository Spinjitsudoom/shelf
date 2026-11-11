"""Share links: a song, an album or a playlist that anyone with the link can listen to, without
an account. Off until an admin turns them on; each link opens only what was shared, can run out
(after a day, a week or a month) and can be stopped at any time. Turning sharing off stops every
link at once (they come back if it's turned on again, unless they've run out).
"""

from __future__ import annotations

import secrets
import time

from .db import get_meta, set_meta

KINDS = ("track", "album", "playlist")


def enabled(conn) -> bool:
    return get_meta(conn, "shares_enabled") == "1"


def set_enabled(conn, on: bool) -> None:
    set_meta(conn, "shares_enabled", "1" if on else "0")


def create(conn, user_id: int, kind: str, item_id: int, days: int | None, now: float | None = None) -> str:
    now = now or time.time()
    token = secrets.token_urlsafe(16)
    conn.execute("INSERT INTO shares(token, user_id, kind, item_id, created_at, expires_at) VALUES(?, ?, ?, ?, ?, ?)",
                 (token, user_id, kind, item_id, now, now + days * 86400 if days else None))
    return token


def find(conn, token: str):
    return conn.execute("SELECT s.*, u.username FROM shares s JOIN users u ON u.id = s.user_id WHERE s.token = ?",
                        (token,)).fetchone()


def expired(row, now: float | None = None) -> bool:
    return row["expires_at"] is not None and row["expires_at"] <= (now or time.time())


def listed(conn, user_id: int | None = None) -> list:
    """Links, newest first: one person's, or everyone's (None)."""
    where, args = ("WHERE s.user_id = ?", (user_id,)) if user_id is not None else ("", ())
    return conn.execute(f"SELECT s.*, u.username FROM shares s JOIN users u ON u.id = s.user_id {where}"
                        " ORDER BY s.created_at DESC, s.rowid DESC", args).fetchall()


def stop(conn, token: str) -> None:
    conn.execute("DELETE FROM shares WHERE token = ?", (token,))


def opened(conn, token: str) -> None:
    conn.execute("UPDATE shares SET opened = opened + 1 WHERE token = ?", (token,))
