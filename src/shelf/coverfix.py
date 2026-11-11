"""Finding covers for albums that have none (or only a small one), from MusicBrainz and the
Cover Art Archive.

A found cover is kept in Shelf's data folder (found-covers/), never written into the music
folders, and wins over the album's own art from then on, rescans included. Taking it away goes
back to the album's own.

The admin picks one from the candidates for an album, or has Shelf look for every album that has
no cover: it only takes a cover when the title and artist match closely, one album a second (as
MusicBrainz asks).
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import urllib.error
import urllib.parse
from pathlib import Path
from typing import Callable

from .releases import AGENT, MB, base_title
from .videos import fold

log = logging.getLogger("shelf.coverfix")
PAUSE = 1.1  # seconds between MusicBrainz lookups


def _get(url: str, timeout: float = 20) -> bytes:
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(25_000_000)


def override_path(found_dir: Path, album_key: str) -> Path:
    return found_dir / (hashlib.sha1(album_key.encode()).hexdigest()[:20] + ".jpg")


def candidates(artist: str, title: str, get: Callable | None = None) -> list[dict]:
    """Release groups on MusicBrainz that could be this album, best first."""
    get = get or _get
    q = f'releasegroup:"{base_title(title) or title}"'
    if fold(artist) not in ("various artists", "unknown artist", ""):
        q += f' AND artist:"{artist}"'
    url = f"{MB}/release-group/?query={urllib.parse.quote(q)}&fmt=json&limit=8"
    data = json.loads(get(url, timeout=20))
    out = []
    for g in data.get("release-groups", []):
        date = g.get("first-release-date") or ""
        out.append({
            "mbid": g["id"], "title": g.get("title", ""), "score": g.get("score", 0),
            "artist": "".join(c.get("name", "") + c.get("joinphrase", "") for c in g.get("artist-credit", [])),
            "year": int(date[:4]) if date[:4].isdigit() else None, "type": g.get("primary-type"),
        })
    return out


def good_match(artist: str, title: str, c: dict) -> bool:
    """Close enough to take without asking: the same title (editions aside) and the same artist."""
    same_title = base_title(c["title"]) == base_title(title)
    a, ca = fold(artist), fold(c["artist"])
    same_artist = a == ca or (a and a in ca) or a in ("various artists", "unknown artist")
    return c.get("score", 0) >= 90 and same_title and bool(same_artist)


def download(mbid: str, get: Callable | None = None) -> bytes | None:
    """The front cover, as large as the archive keeps (1200 px), else smaller."""
    get = get or _get
    for size in ("front-1200", "front-500", "front"):
        try:
            return get(f"https://coverartarchive.org/release-group/{mbid}/{size}", timeout=30)
        except (urllib.error.URLError, OSError):
            continue
    return None


def save(found_dir: Path, album_key: str, data: bytes) -> Path:
    """Keeps a found cover (as a JPEG, at most 1600 px)."""
    import io

    from PIL import Image

    img = Image.open(io.BytesIO(data)).convert("RGB")
    img.thumbnail((1600, 1600))
    found_dir.mkdir(parents=True, exist_ok=True)
    path = override_path(found_dir, album_key)
    part = path.with_suffix(".part")
    img.save(part, "JPEG", quality=90)
    part.replace(path)
    return path


class Finder:
    """Looks for covers for every album without one, in the background."""

    def __init__(self, albums: Callable[[], list[dict]], apply: Callable[[dict, str], None]):
        self.albums, self.apply = albums, apply
        self.state = {"running": False, "done": 0, "total": 0, "found": 0, "finishedAt": None}
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        if self.state["running"]:
            return False
        todo = self.albums()
        self.state = {"running": True, "done": 0, "total": len(todo), "found": 0, "finishedAt": None}
        self._thread = threading.Thread(target=self._run, args=(todo,), name="shelf-covers", daemon=True)
        self._thread.start()
        return True

    def wait(self, timeout: float = 30) -> None:
        if self._thread:
            self._thread.join(timeout)

    def _run(self, todo: list[dict]) -> None:
        try:
            for album in todo:
                try:
                    best = next((c for c in candidates(album["artist"], album["title"], get=_get)
                                 if good_match(album["artist"], album["title"], c)), None)
                    if best:
                        data = download(best["mbid"], get=_get)
                        if data:
                            self.apply(album, data)
                            self.state["found"] += 1
                except (urllib.error.URLError, OSError, ValueError) as e:
                    log.info("Couldn’t look up a cover for %s: %s", album["title"], e)
                self.state["done"] += 1
                time.sleep(PAUSE)
        finally:
            self.state["running"] = False
            self.state["finishedAt"] = time.time()
