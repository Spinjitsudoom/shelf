"""Requests: music people in the household ask for — an artist, or one album in particular.
Everyone sees the list (so nobody asks twice), admins mark requests done or declined, and a scan
that brings the music in marks the request done by itself.
"""

from __future__ import annotations

import time

from .imports import fold

STATUSES = ("open", "done", "declined")


def create(conn, user_id: int, artist: str, album: str | None, note: str, now: float | None = None) -> int:
    cur = conn.execute("INSERT INTO requests(user_id, artist, album, note, status, created_at) VALUES(?, ?, ?, ?, 'open', ?)",
                       (user_id, artist, album, note, now or time.time()))
    return cur.lastrowid


def find(conn, rid: int):
    return conn.execute("SELECT r.*, u.username FROM requests r JOIN users u ON u.id = r.user_id WHERE r.id = ?",
                        (rid,)).fetchone()


def listed(conn) -> list:
    """Everyone's requests: open first, then newest first."""
    return conn.execute("""SELECT r.*, u.username FROM requests r JOIN users u ON u.id = r.user_id
                           ORDER BY r.status != 'open', r.created_at DESC, r.id DESC""").fetchall()


def open_duplicate(conn, artist: str, album: str | None):
    """The open request already asking for this, if there is one."""
    for row in conn.execute("SELECT r.*, u.username FROM requests r JOIN users u ON u.id = r.user_id WHERE r.status = 'open'"):
        if fold(row["artist"]) == fold(artist) and fold(row["album"] or "") == fold(album or ""):
            return row
    return None


def set_status(conn, rid: int, status: str, now: float | None = None) -> None:
    conn.execute("UPDATE requests SET status = ?, resolved_at = ? WHERE id = ?",
                 (status, None if status == "open" else (now or time.time()), rid))


def remove(conn, rid: int) -> None:
    conn.execute("DELETE FROM requests WHERE id = ?", (rid,))


def _shelved(conn) -> tuple[set[str], set[str]]:
    """What's on the shelf, folded: the artists, and the artist+album pairs."""
    artists, albums = set(), set()
    for r in conn.execute("SELECT DISTINCT artist, title FROM albums"):
        artists.add(fold(r["artist"]))
        albums.add((fold(r["artist"]), fold(r["title"])))
    for r in conn.execute("SELECT DISTINCT artist, album_artist FROM tracks"):
        artists.add(fold(r["artist"]))
        if r["album_artist"]:
            artists.add(fold(r["album_artist"]))
    return artists, albums


def on_shelf(conn, artist: str, album: str | None) -> bool:
    artists, albums = _shelved(conn)
    if album:
        return (fold(artist), fold(album)) in albums
    return fold(artist) in artists


def fulfil(conn, now: float | None = None) -> list:
    """Open requests the library now answers, marked done. Called after every scan."""
    pending = [r for r in listed(conn) if r["status"] == "open"]
    if not pending:
        return []
    artists, albums = _shelved(conn)
    got = [r for r in pending
           if ((fold(r["artist"]), fold(r["album"])) in albums if r["album"] else fold(r["artist"]) in artists)]
    for r in got:
        set_status(conn, r["id"], "done", now)
    return got
