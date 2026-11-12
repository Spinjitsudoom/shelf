"""Requests: music people in the household ask for — an artist, or one album in particular.
Everyone sees the list (so nobody asks twice), admins mark requests done or declined, and a scan
that brings the music in marks the request done by itself.

While someone types, MusicBrainz (the open music encyclopedia) suggests the artist or album they
mean, so a request names the exact thing, with its year and cover. Only what's typed is sent.
Typing a name MusicBrainz doesn't know still makes a request.
"""

from __future__ import annotations

import re
import threading
import time

from . import releases
from .imports import fold

STATUSES = ("open", "done", "declined")
MBID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def create(conn, user_id: int, artist: str, album: str | None, note: str, now: float | None = None, *,
           artist_id: str | None = None, album_id: str | None = None, year: int | None = None,
           kind: str | None = None) -> int:
    cur = conn.execute("""INSERT INTO requests(user_id, artist, album, note, status, created_at, artist_mbid, album_mbid, year, kind)
                          VALUES(?, ?, ?, ?, 'open', ?, ?, ?, ?, ?)""",
                       (user_id, artist, album, note, now or time.time(), artist_id, album_id, year, kind))
    return cur.lastrowid


def find(conn, rid: int):
    return conn.execute("SELECT r.*, u.username FROM requests r JOIN users u ON u.id = r.user_id WHERE r.id = ?",
                        (rid,)).fetchone()


def listed(conn) -> list:
    """Everyone's requests: open first, then newest first."""
    return conn.execute("""SELECT r.*, u.username FROM requests r JOIN users u ON u.id = r.user_id
                           ORDER BY r.status != 'open', r.created_at DESC, r.id DESC""").fetchall()


def open_duplicate(conn, artist: str, album: str | None, album_id: str | None = None):
    """The open request already asking for this, if there is one."""
    for row in conn.execute("SELECT r.*, u.username FROM requests r JOIN users u ON u.id = r.user_id WHERE r.status = 'open'"):
        if album_id and row["album_mbid"] == album_id:
            return row
        if fold(row["artist"]) == fold(artist) and fold(row["album"] or "") == fold(album or ""):
            return row
    return None


def set_status(conn, rid: int, status: str, now: float | None = None) -> None:
    conn.execute("UPDATE requests SET status = ?, resolved_at = ? WHERE id = ?",
                 (status, None if status == "open" else (now or time.time()), rid))


def remove(conn, rid: int) -> None:
    conn.execute("DELETE FROM requests WHERE id = ?", (rid,))


class Shelf:
    """What's on the shelf, for telling whether a request is already answered."""

    def __init__(self, conn):
        rows = conn.execute("SELECT artist, title FROM albums").fetchall()
        self.albums = [(releases.fold(r["artist"]), releases.base_title(r["title"])) for r in rows]
        self.artists = {fold(r["artist"]) for r in rows}
        for r in conn.execute("SELECT DISTINCT artist, album_artist FROM tracks"):
            self.artists.add(fold(r["artist"]))
            if r["album_artist"]:
                self.artists.add(fold(r["album_artist"]))

    def has(self, artist: str, album: str | None) -> bool:
        if album:  # "Discovery (Deluxe Edition)" on the shelf answers a request for "Discovery"
            return releases.owns(self.albums, artist, album)
        return fold(artist) in self.artists


def on_shelf(conn, artist: str, album: str | None) -> bool:
    return Shelf(conn).has(artist, album)


def fulfil(conn, now: float | None = None) -> list:
    """Open requests the library now answers, marked done. Called after every scan."""
    pending = [r for r in listed(conn) if r["status"] == "open"]
    if not pending:
        return []
    shelf = Shelf(conn)
    got = [r for r in pending if shelf.has(r["artist"], r["album"])]
    for r in got:
        set_status(conn, r["id"], "done", now)
    return got


# ---------- suggestions from MusicBrainz ----------

_cache: dict[tuple, tuple[float, list]] = {}
_cache_lock = threading.Lock()
SEARCH_KEEP = 3600
ALBUMS_KEEP = 86400


def _remember(key: tuple, keep: float, fetch) -> list:
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < keep:
            return hit[1]
    got = fetch()
    with _cache_lock:
        if len(_cache) > 500:
            _cache.clear()
        _cache[key] = (now, got)
    return got


def _escape(text: str) -> str:
    """Typed text as a MusicBrainz (Lucene) search, with its special characters taken literally."""
    return re.sub(r'([+\-&|!(){}\[\]^"~*?:\\/])', r"\\\1", text.strip())


def _year(date: str | None) -> int | None:
    return int(date[:4]) if date and date[:4].isdigit() else None


def find_artists(q: str, mb=None) -> list[dict]:
    """Artists whose name matches what's typed, best match first."""
    mb = mb or releases.mb

    def fetch():
        r = mb("artist", query=_escape(q), limit=8, retries=2)
        out = []
        for a in r.get("artists", []):
            if a.get("score", 0) < 60:
                continue
            born = _year((a.get("life-span") or {}).get("begin"))
            about = [a.get("disambiguation"), a.get("type"), (a.get("area") or {}).get("name"), str(born) if born else None]
            out.append({"id": a["id"], "name": a["name"], "about": ", ".join(x for x in about if x)})
        return out
    return _remember(("artist", fold(q)), SEARCH_KEEP, fetch)


def artist_albums(artist_id: str, mb=None) -> list[dict]:
    """One artist's albums and EPs: the studio ones first, then live albums, compilations and
    the rest, newest first within each."""
    mb = mb or releases.mb

    def fetch():
        # website-default: what MusicBrainz's own pages list, so bootleg-only albums stay out.
        r = mb("release-group", artist=artist_id, type="album|ep", limit=100, retries=2,
               **{"release-group-status": "website-default"})
        out = []
        for g in r.get("release-groups", []):
            extra = g.get("secondary-types") or []
            if "Interview" in extra:
                continue
            out.append({"id": g["id"], "title": g["title"], "year": _year(g.get("first-release-date")),
                        "type": g.get("primary-type") or "Album", "extra": ", ".join(extra)})
        out.sort(key=lambda a: (bool(a["extra"]), -(a["year"] or 0)))
        return out
    return _remember(("albums", artist_id), ALBUMS_KEEP, fetch)


def find_albums(q: str, artist: str = "", mb=None) -> list[dict]:
    """Albums whose title matches what's typed (by this artist, when one's typed too)."""
    mb = mb or releases.mb

    def fetch():
        query = f"releasegroup:({_escape(q)}) AND (primarytype:album OR primarytype:ep)"
        if artist.strip():
            query += f" AND artist:({_escape(artist)})"
        r = mb("release-group", query=query, limit=10, retries=2)
        out = []
        for g in r.get("release-groups", []):
            if g.get("score", 0) < 50:
                continue
            credit = g.get("artist-credit") or []
            name = "".join(c.get("name", "") + c.get("joinphrase", "") for c in credit)
            first = (credit[0].get("artist") or {}).get("id") if credit else None
            out.append({"id": g["id"], "title": g["title"], "year": _year(g.get("first-release-date")),
                        "type": g.get("primary-type") or "Album", "extra": ", ".join(g.get("secondary-types") or []),
                        "artist": name, "artistId": first})
        return out
    return _remember(("album", fold(q), fold(artist)), SEARCH_KEEP, fetch)
