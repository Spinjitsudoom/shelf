"""Following artists: the artists someone follows make up their Library, so it shows what they
care about instead of everything on the server.

A follow is the same thing as a star on the artist in a Subsonic app (the `stars` table, kind
'artist', keyed by the folded name so it survives rescans and spelling of case and accents).
"""

from __future__ import annotations

import time

from .videos import fold


def followed(conn, user_id: int) -> set[str]:
    """The folded names of the artists this person follows."""
    return {r[0] for r in conn.execute("SELECT ref FROM stars WHERE user_id = ? AND kind = 'artist'", (user_id,))}


def is_following(conn, user_id: int, name: str) -> bool:
    return conn.execute("SELECT 1 FROM stars WHERE user_id = ? AND kind = 'artist' AND ref = ?",
                        (user_id, fold(name))).fetchone() is not None


def follow(conn, user_id: int, name: str, now: float | None = None) -> None:
    conn.execute("INSERT OR IGNORE INTO stars(user_id, kind, ref, at) VALUES(?, 'artist', ?, ?)",
                 (user_id, fold(name), now or time.time()))


def unfollow(conn, user_id: int, name: str) -> None:
    conn.execute("DELETE FROM stars WHERE user_id = ? AND kind = 'artist' AND ref = ?", (user_id, fold(name)))
