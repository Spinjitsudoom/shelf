"""Songs an imported playlist asked for that aren't in the library yet.

They stay in the playlist, where they were, marked missing (table playlist_missing; their
`position` shares the number line with playlist_tracks, so the two interleave). Nothing plays
them and Subsonic apps don't see them. A scan that brings a song in puts the real song in its
place.

Each missing song also asks for its album in Requests (requests.py), for the person who
imported it: the album the import named (a CSV export, a playlist file's tags), or else the one
MusicBrainz says the song first came out on (when artist info is on). Failing that, the artist.
Already on the shelf or already asked for: no new request; the song points at the open one.
"""

from __future__ import annotations

import bisect
import logging
import re
import time

from . import imports, releases
from . import requests as wishlist

log = logging.getLogger("shelf.missing")

_DASH = re.compile(r"^(.+?)\s+[-–—]\s+(.+)$")
LOOKUP_LIMIT = 300  # MusicBrainz lookups for one import (one a second)


# ---------- the playlist's missing songs ----------

def add(conn, pid: int, user_id: int, wanted: list[dict], positions: list[float], now: float | None = None) -> list[int]:
    """Missing songs (imports.want dicts) into a playlist at these positions. Their ids."""
    now = now or time.time()
    ids = []
    for w, pos in zip(wanted, positions):
        cur = conn.execute(
            """INSERT INTO playlist_missing(playlist_id, position, artist, title, album, duration, text, path, added_at, added_by)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (pid, pos, w["artist"], w["title"], w["album"], w["duration"], w["text"], w["path"], now, user_id))
        ids.append(cur.lastrowid)
    return ids


def want_of(row) -> dict:
    return imports.want(artist=row["artist"], title=row["title"], album=row["album"], duration=row["duration"],
                        text=row["text"], path=row["path"])


def listed(conn, pid: int) -> list:
    return conn.execute("""SELECT m.*, r.status AS request_status FROM playlist_missing m
                           LEFT JOIN requests r ON r.id = m.request_id
                           WHERE m.playlist_id = ? ORDER BY m.position, m.id""", (pid,)).fetchall()


def as_json(rows, track_positions: list[float]) -> list[dict]:
    """Missing songs for the app. `after`: how many of the playlist's real songs come before it."""
    out = []
    for r in rows:
        w = want_of(r)
        artist, title = guess(w)
        out.append({"id": r["id"], "after": bisect.bisect_left(track_positions, r["position"]),
                    "title": w["title"] or title or imports.label(w), "artist": w["artist"] or artist,
                    "album": w["album"] or None, "duration": w["duration"], "addedAt": r["added_at"],
                    "requestId": r["request_id"], "request": r["request_status"]})
    return out


def count(conn, pid: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM playlist_missing WHERE playlist_id = ?", (pid,)).fetchone()[0]


def remove(conn, pid: int, mid: int) -> bool:
    return conn.execute("DELETE FROM playlist_missing WHERE id = ? AND playlist_id = ?", (mid, pid)).rowcount > 0


def end(conn, pid: int) -> float:
    """The last position used in the playlist, by a real song or a missing one."""
    return conn.execute("""SELECT MAX(COALESCE((SELECT MAX(position) FROM playlist_tracks WHERE playlist_id = ?1), 0),
                                      COALESCE((SELECT MAX(position) FROM playlist_missing WHERE playlist_id = ?1), 0))""",
                        (pid,)).fetchone()[0]


def anchors(conn, pid: int) -> list[tuple[int, int | None]]:
    """Each missing song and the real entry just before it, so they can stay together while
    the real songs are renumbered (reorder)."""
    entries = conn.execute("SELECT id, position FROM playlist_tracks WHERE playlist_id = ? ORDER BY position", (pid,)).fetchall()
    positions = [e["position"] for e in entries]
    out = []
    for m in conn.execute("SELECT id, position FROM playlist_missing WHERE playlist_id = ? ORDER BY position, id", (pid,)):
        i = bisect.bisect_left(positions, m["position"])
        out.append((m["id"], entries[i - 1]["id"] if i else None))
    return out


def reanchor(conn, pid: int, kept: list[tuple[int, int | None]]) -> None:
    """Missing songs back after the entries they followed, wherever those went."""
    pos = {r["id"]: r["position"] for r in conn.execute("SELECT id, position FROM playlist_tracks WHERE playlist_id = ?", (pid,))}
    groups: dict[int | None, list[int]] = {}
    for mid, entry in kept:
        groups.setdefault(entry if entry in pos else None, []).append(mid)
    rows = []
    for entry, mids in groups.items():
        base = pos[entry] if entry is not None else 0
        step = 1 / (len(mids) + 1)  # real songs are numbered 1, 2, 3…: fit between them
        rows += [(base + step * (k + 1), mid) for k, mid in enumerate(mids)]
    conn.executemany("UPDATE playlist_missing SET position = ? WHERE id = ?", rows)


def fill(conn, now: float | None = None) -> int:
    """Missing songs the library has now, swapped for the real song in the same place. Called
    after every scan. How many were filled in."""
    rows = conn.execute("SELECT * FROM playlist_missing").fetchall()
    if not rows:
        return 0
    library = imports.Library(conn.execute(
        "SELECT id, title, artist, album_artist, album, duration, path FROM tracks"))
    now = now or time.time()
    filled = 0
    for r in rows:
        tid = library.find(want_of(r))
        if tid is None:
            continue
        there = conn.execute("SELECT 1 FROM playlist_tracks WHERE playlist_id = ? AND track_id = ?",
                             (r["playlist_id"], tid)).fetchone()
        if not there:  # added by hand meanwhile: just drop the placeholder
            conn.execute("""INSERT INTO playlist_tracks(playlist_id, track_id, position, added_at, added_by)
                            VALUES(?, ?, ?, ?, ?)""", (r["playlist_id"], tid, r["position"], now, r["added_by"]))
        conn.execute("DELETE FROM playlist_missing WHERE id = ?", (r["id"],))
        filled += 1
    return filled


# ---------- asking for their albums ----------

def guess(w: dict) -> tuple[str, str]:
    """Artist and title, also for a song known only by a line of text such as a video title
    ("Queen - Bohemian Rhapsody (Official Video)"). Either may be empty."""
    if w["title"]:
        return w["artist"], imports.core(w["title"])
    text = w["text"]
    if not text and w["path"]:  # a file from another player: its name, without the number
        name = w["path"].replace("\\", "/").rsplit("/", 1)[-1]
        text = re.sub(r"^\s*\d{1,3}(?:[-.]\d{1,3})?\s*[-._)]*\s*", "", re.sub(r"\.[A-Za-z0-9]{1,5}$", "", name))
    m = _DASH.match(text)
    if m:
        return m.group(1).strip(), imports.core(m.group(2)).strip()
    return w["artist"], imports.core(text).strip()


def _rank(rel: dict) -> tuple:
    """Which release a song "belongs" on: an official studio album, then an EP, then a single;
    compilations, soundtracks and live albums last. The first one out wins a tie."""
    g = rel.get("release-group") or {}
    kind, extra = g.get("primary-type") or "", g.get("secondary-types") or []
    order = 4 if extra else {"Album": 0, "EP": 1, "Single": 2}.get(kind, 5)
    return (rel.get("status") != "Official", order, rel.get("date") or "9999")


def candidates(w: dict) -> list[tuple[str, str]]:
    """The (artist, title) a missing song might be, likeliest first: a pasted "A - B" can be
    either way round."""
    artist, title = guess(w)
    out = [(artist, title)] if artist and title else []
    if not w["title"]:
        m = _DASH.match(w["text"] or "")
        if m:
            out.append((m.group(2).strip(), imports.core(m.group(1)).strip()))
    return out


def album_of(artist: str, title: str, mb=None) -> dict | None:
    """The album a song came out on, from MusicBrainz: {artist, artistId, album, albumId, year,
    kind}. The title must match and the artist be among those credited."""
    mb = mb or releases.mb
    if not title or not artist:
        return None
    query = f"recording:({wishlist._escape(title)}) AND artist:({wishlist._escape(artist)})"
    r = mb("recording", query=query, limit=15, retries=2)
    want_title, want_names = imports.fold(imports.core(title)), imports.artist_names(artist)
    best = None
    for rec in r.get("recordings", []):
        if rec.get("score", 0) < 70:
            continue
        if not imports.close(imports.fold(imports.core(rec.get("title", ""))), want_title):
            continue
        credit = rec.get("artist-credit") or []
        name = "".join(c.get("name", "") + c.get("joinphrase", "") for c in credit)
        if not (imports.artist_names(name) & want_names):
            continue
        for rel in rec.get("releases") or []:
            g = rel.get("release-group") or {}
            if not g.get("id") or not g.get("title"):
                continue
            key = _rank(rel)
            if best is None or key < best[0]:
                first = (credit[0].get("artist") or {}).get("id") if credit else None
                best = (key, {"artist": name or artist, "artistId": first, "album": g["title"], "albumId": g["id"],
                              "year": wishlist._year(rel.get("date")), "kind": g.get("primary-type") or None})
    return best[1] if best else None


def plan(w: dict, lookup: bool) -> str:
    """How a missing song gets its request: "album" (the import named it), "lookup" (ask
    MusicBrainz), "artist" (just the artist) or "" (nothing to go on)."""
    artist, title = guess(w)
    if w["album"] and artist:
        return "album"
    if lookup and artist and title:
        return "lookup"
    # A song known only by a line of text names no artist we can trust (a channel isn't one).
    return "artist" if w["artist"] and w["title"] else ""


def ask(conn, user_id: int, mids: list[int], target: dict, note: str, shelf=None) -> int | None:
    """One request for missing songs: made, or the open one already asking for it. Nothing
    when the shelf has it already. The request's id."""
    artist, album = target["artist"].strip(), (target.get("album") or "").strip() or None
    if not artist:
        return None
    shelf = shelf or wishlist.Shelf(conn)
    if shelf.has(artist, album):
        return None
    earlier = wishlist.open_duplicate(conn, artist, album, target.get("albumId") if album else None)
    if earlier is not None:
        rid = earlier["id"]
    else:
        rid = wishlist.create(conn, user_id, artist, album, note, artist_id=target.get("artistId"),
                              album_id=target.get("albumId") if album else None,
                              year=target.get("year") if album else None,
                              kind=target.get("kind") if album else None)
    conn.executemany("UPDATE playlist_missing SET request_id = ? WHERE id = ?", [(rid, m) for m in mids])
    return rid


def request_now(conn, user_id: int, playlist: str, missing: list[tuple[int, dict]], lookup: bool) -> list[tuple[int, dict]]:
    """Requests for the missing songs that need no lookup. Returns those that need MusicBrainz."""
    note = f"For the playlist ‘{playlist}’"
    later, groups = [], {}
    for mid, w in missing:
        how = plan(w, lookup)
        if how == "lookup":
            later.append((mid, w))
        elif how:
            artist, _ = guess(w)
            album = w["album"] if how == "album" else ""
            groups.setdefault((imports.fold(artist), imports.fold(album)), ({"artist": artist, "album": album}, []))[1].append(mid)
    if groups:
        shelf = wishlist.Shelf(conn)
        for target, mids in groups.values():
            ask(conn, user_id, mids, target, note, shelf)
    return later


def request_looked_up(connect, user_id: int, playlist: str, missing: list[tuple[int, dict]], mb=None) -> int:
    """Requests for missing songs whose album MusicBrainz has to name (slow: one lookup a
    second, so it runs in the background). `connect()` gives a database session. Songs it
    can't place are asked for by artist. How many requests now point at them."""
    note = f"For the playlist ‘{playlist}’"
    seen: dict[tuple, dict | None] = {}
    groups: dict[tuple, tuple[dict, list[int]]] = {}
    lookups = 0
    for mid, w in missing:
        target = None
        for artist, title in candidates(w):
            key = (imports.fold(artist), imports.fold(title))
            if key not in seen:
                seen[key] = None
                if lookups < LOOKUP_LIMIT:
                    lookups += 1
                    try:
                        seen[key] = album_of(artist, title, mb=mb)
                    except (OSError, ValueError) as e:  # URLError is an OSError
                        log.info("MusicBrainz lookup for %s - %s failed: %s", artist, title, e)
            target = seen[key]
            if target:
                break
        if target is None:
            if not (w["artist"] and w["title"]):
                continue  # only a video title: no artist to ask for
            target = {"artist": w["artist"], "album": ""}
        gkey = (target.get("albumId") or imports.fold(target["artist"]), imports.fold(target.get("album") or ""))
        groups.setdefault(gkey, (target, []))[1].append(mid)
    asked = 0
    with connect() as conn:
        shelf = wishlist.Shelf(conn)
        for target, mids in groups.values():
            # The playlist may have been deleted meanwhile; its missing songs went with it.
            mids = [m for m in mids if conn.execute("SELECT 1 FROM playlist_missing WHERE id = ?", (m,)).fetchone()]
            if mids and ask(conn, user_id, mids, target, note, shelf) is not None:
                asked += 1
    return asked
