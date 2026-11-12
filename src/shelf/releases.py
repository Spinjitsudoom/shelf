"""New releases from your artists: albums and EPs by the artists on the shelf that aren't on
it yet, from MusicBrainz (the open music encyclopedia), with covers from the Cover Art Archive.

Checked once a day in the background (MusicBrainz asks for at most one request a second, so
a library with many artists takes a while), and on request from the admin dashboard. Only
artist names are sent. Off when `artist_info` is off in config.toml.

The same check learns each artist's genres (MusicBrainz's, most votes first), once a month per
artist, for suggestions and Make a playlist (see genres.py).
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import __version__
from .db import get_meta, session, set_meta
from .videos import fold

log = logging.getLogger("shelf.releases")
MB = "https://musicbrainz.org/ws/2"
AGENT = f"Shelf/{__version__} (self-hosted music server)"
DAY = 86400
SKIP = {"various artists", "various", "soundtrack", "unknown artist"}
GENRES_EVERY = 30 * DAY


def artist_genres(db_path: Path) -> dict[str, list[str]]:
    """{folded artist name: their MusicBrainz genres, most votes first}."""
    with session(db_path) as conn:
        known = json.loads(get_meta(conn, "mb_artist_genres") or "{}")
    return {k: v["genres"] for k, v in known.items() if v.get("genres")}


def _get(url: str, timeout: float = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


_mb_lock = threading.Lock()
_mb_last = 0.0


def mb(path: str, retries: int = 4, **params) -> dict:
    """One MusicBrainz call. Everything in Shelf goes through here, so together it keeps to
    MusicBrainz's limit of one request a second."""
    global _mb_last
    q = urllib.parse.urlencode({**params, "fmt": "json"})
    for attempt in range(retries):
        with _mb_lock:
            wait = 1.1 - (time.monotonic() - _mb_last)
            if wait > 0:
                time.sleep(wait)
            _mb_last = time.monotonic()
        try:
            return json.loads(_get(f"{MB}/{path}?{q}"))
        except urllib.error.HTTPError as e:
            if e.code not in (429, 503) or attempt == retries - 1:
                raise
            time.sleep(2 + attempt * 3)  # MusicBrainz is busy: back off and try again
    raise OSError("MusicBrainz is busy")


def base_title(title: str) -> str:
    """"Paranoid (2009 Remaster) [Deluxe]" -> "paranoid", for matching what's on the shelf."""
    t = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", title or "")
    t = re.sub(r"\s+-\s+(single|ep|deluxe.*|remaster.*|\d{4} remaster.*)$", "", t, flags=re.I)
    return fold(t).strip()


def owns(albums: list[tuple[str, str]], artist: str, title: str) -> bool:
    """Whether the shelf has this release: same title, by this artist or a credit that
    includes them ("One More Time" by "Aerosmith & Yungblud" counts for YUNGBLUD)."""
    a, t = fold(artist), base_title(title)
    return any(bt == t and (fa == a or re.search(rf"(?<![a-z0-9]){re.escape(a)}(?![a-z0-9])", fa)) for fa, bt in albums)


class Releases:
    def __init__(self, db_path: Path, enabled: bool = True):
        self.db_path = db_path
        self.enabled = enabled
        self.state = {"running": False, "checked": 0, "total": 0}
        self._wake = threading.Event()
        self._stop = threading.Event()

    def start(self) -> None:
        if self.enabled:
            threading.Thread(target=self._loop, name="shelf-releases", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def check_now(self) -> None:
        self._wake.set()

    def _loop(self) -> None:
        self._wake.wait(60)  # let the first scan go first (unless someone asks to check now)
        while not self._stop.is_set():
            with session(self.db_path) as conn:
                last = float(get_meta(conn, "releases_checked") or 0)
            if time.time() - last > DAY or self._wake.is_set():
                self._wake.clear()
                try:
                    self.refresh()
                except Exception:
                    log.exception("Checking for new releases failed")
            self._wake.wait(3600)

    def _mb(self, path: str, **params) -> dict:
        return mb(path, **params)

    def _artist_id(self, name: str, cache: dict) -> str | None:
        key = fold(name)
        if key in cache:
            return cache[key]
        r = self._mb("artist", query=f'artist:"{name}"', limit=3)
        best = next((a for a in r.get("artists", []) if a.get("score", 0) >= 95 and fold(a.get("name", "")) == key), None)
        cache[key] = best["id"] if best else None
        return cache[key]

    def refresh(self) -> list[dict]:
        with session(self.db_path) as conn:
            rows = conn.execute("SELECT artist, title FROM albums").fetchall()
            ids = json.loads(get_meta(conn, "mb_artist_ids") or "{}")
            genres = json.loads(get_meta(conn, "mb_artist_genres") or "{}")
        owned: dict[str, set[str]] = {}
        names: dict[str, str] = {}
        shelf = [(fold(r["artist"]), base_title(r["title"])) for r in rows]
        for r in rows:
            k = fold(r["artist"])
            if k in SKIP:
                continue
            owned.setdefault(k, set()).add(base_title(r["title"]))
            names.setdefault(k, r["artist"])
        self.state.update(running=True, checked=0, total=len(names))
        found: list[dict] = []
        try:
            for key, name in sorted(names.items()):
                if self._stop.is_set():
                    break
                try:
                    mbid = self._artist_id(name, ids)
                    if mbid and time.time() - genres.get(key, {}).get("at", 0) > GENRES_EVERY:
                        a = self._mb(f"artist/{mbid}", inc="genres")
                        voted = sorted((g for g in a.get("genres") or [] if g.get("count", 0) > 0), key=lambda g: -g["count"])
                        genres[key] = {"genres": [g["name"] for g in voted[:6]], "at": time.time()}
                    if mbid:
                        r = self._mb("release-group", artist=mbid, type="album|ep", limit=100)
                        for g in r.get("release-groups", []):
                            if set(g.get("secondary-types") or []) & {"Compilation", "Live", "Remix", "DJ-mix", "Demo", "Interview"}:
                                continue
                            if owns(shelf, name, g.get("title", "")) or not g.get("first-release-date"):
                                continue
                            found.append({"artist": name, "title": g["title"], "date": g["first-release-date"],
                                          "type": g.get("primary-type") or "Album", "mbid": g["id"], "artistId": mbid})
                except (urllib.error.URLError, OSError, ValueError) as e:
                    log.warning("MusicBrainz lookup for %s failed: %s", name, e)
                self.state["checked"] += 1
        finally:
            self.state["running"] = False
        found.sort(key=lambda x: x["date"], reverse=True)
        with session(self.db_path) as conn:
            set_meta(conn, "releases", json.dumps(found))
            set_meta(conn, "releases_checked", str(time.time()))
            set_meta(conn, "mb_artist_ids", json.dumps(ids))
            set_meta(conn, "mb_artist_genres", json.dumps(genres))
        log.info("Found %d releases by your artists that aren't on the shelf", len(found))
        return found

    def get(self) -> dict:
        with session(self.db_path) as conn:
            found = json.loads(get_meta(conn, "releases") or "[]")
            checked = get_meta(conn, "releases_checked")
            shelf = [(fold(r["artist"]), base_title(r["title"])) for r in conn.execute("SELECT artist, title FROM albums")]
        # Albums added since the last check drop off at once.
        found = [f for f in found if not owns(shelf, f["artist"], f["title"])]
        return {"releases": found, "checkedAt": float(checked) if checked else None, "state": self.state}


_covers_lock = threading.Lock()


def cover(cache_dir: Path, mbid: str) -> bytes | None:
    """A release's front cover (250 px) from the Cover Art Archive, cached on disk."""
    if not re.fullmatch(r"[0-9a-f-]{36}", mbid):
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{mbid}.jpg"
    miss = cache_dir / f"{mbid}.none"
    if path.exists():
        return path.read_bytes()
    if miss.exists() and time.time() - miss.stat().st_mtime < 7 * DAY:
        return None
    try:
        data = _get(f"https://coverartarchive.org/release-group/{mbid}/front-250", timeout=20)
    except (urllib.error.URLError, OSError):
        miss.touch()
        return None
    with _covers_lock:
        path.write_bytes(data)
    return data
