"""About the artist: a short biography and photo from Wikipedia.

Only the artist's name is sent. Wikipedia pages are checked to really be about a musician
or band ("Slipknot" alone is a knot), the answer is cached in the database, and the photo
is downloaded once and served by Shelf, so browsers never contact Wikipedia themselves.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .db import session
from .videos import fold

log = logging.getLogger("shelf.artists")

UA = "Shelf/0.5 (self-hosted music server)"
API = "https://en.wikipedia.org"
RETRY_MISS_AFTER = 30 * 86400
REFRESH_AFTER = 90 * 86400
OFFLINE_BACKOFF = 300
_MUSIC = re.compile(
    r"\b(band|singer|musician|rapper|songwriter|group|duo|trio|dj|producer|composer|guitarist|"
    r"vocalist|drummer|music|rock|metal|pop|punk|hip hop|rap|jazz|country|electronic|orchestra|choir)\b",
    re.I,
)
_offline_until = 0.0


def _get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as res:
            return json.load(res)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def _summary(title: str) -> dict | None:
    return _get_json(f"{API}/api/rest_v1/page/summary/{urllib.parse.quote(title.replace(' ', '_'), safe='')}")


def _is_artist_page(page: dict | None, name: str) -> bool:
    if not page or page.get("type") != "standard":
        return False
    title = re.sub(r"\s*\([^)]*\)$", "", page.get("title", ""))
    if fold(title) != fold(name):
        return False
    return bool(_MUSIC.search(page.get("description") or "") or _MUSIC.search((page.get("extract") or "")[:300]))


def _find_page(name: str) -> dict | None:
    for suffix in ("", " (band)", " (musician)", " (singer)", " (rapper)", " (group)"):
        page = _summary(name + suffix)
        if _is_artist_page(page, name):
            return page
    q = urllib.parse.urlencode({"action": "query", "list": "search", "format": "json", "srlimit": 5,
                                "srsearch": f'"{name}" band OR singer OR musician OR rapper'})
    for r in ((_get_json(f"{API}/w/api.php?{q}") or {}).get("query", {}).get("search", [])):
        page = _summary(r["title"])
        if _is_artist_page(page, name):
            return page
    return None


def image_path(data_dir: Path, name: str) -> Path:
    return data_dir / "artists" / (hashlib.sha1(fold(name).encode()).hexdigest()[:16] + ".webp")


def _save_image(url: str, dest: Path) -> bool:
    from PIL import Image

    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as res:
        data = res.read(15_000_000)
    img = Image.open(io.BytesIO(data)).convert("RGB")
    img.thumbnail((1600, 1600))
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "WEBP", quality=82)
    return True


def cached(db_path: Path, key: str, kind: str):
    with session(db_path) as conn:
        row = conn.execute("SELECT fetched_at, data FROM artist_cache WHERE key = ? AND kind = ?", (key, kind)).fetchone()
    if not row:
        return None, None
    return row["fetched_at"], (json.loads(row["data"]) if row["data"] else None)


def store(db_path: Path, key: str, kind: str, data) -> None:
    with session(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO artist_cache(key, kind, fetched_at, data) VALUES(?, ?, ?, ?)",
            (key, kind, time.time(), json.dumps(data) if data is not None else None),
        )


def about(db_path: Path, data_dir: Path, name: str) -> dict | None:
    """{name, description, extract, url, hasImage} for an artist, or None."""
    global _offline_until
    key = fold(name)
    at, data = cached(db_path, key, "about")
    age = time.time() - at if at else None
    if age is not None and (age < (REFRESH_AFTER if data else RETRY_MISS_AFTER)):
        return data
    if time.time() < _offline_until:
        return data
    try:
        page = _find_page(name)
    except (OSError, ValueError) as e:
        _offline_until = time.time() + OFFLINE_BACKOFF
        log.info("Wikipedia unavailable (%s)", e)
        return data
    if not page:
        store(db_path, key, "about", None)
        return None
    img = (page.get("originalimage") or page.get("thumbnail") or {}).get("source")
    has_image = False
    if img:
        try:
            has_image = _save_image(img, image_path(data_dir, name))
        except Exception as e:
            log.info("Couldn't fetch the photo of %s: %s", name, e)
    data = {
        "name": name,
        "title": page.get("title"),
        "description": page.get("description") or "",
        "extract": page.get("extract") or "",
        "url": ((page.get("content_urls") or {}).get("desktop") or {}).get("page"),
        "hasImage": has_image,
    }
    store(db_path, key, "about", data)
    return data
