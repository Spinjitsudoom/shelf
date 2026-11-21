"""About the artist: a short biography and photo from Wikipedia.

Only the artist's name is sent. Wikipedia pages are checked to really be about a musician
or band ("Slipknot" alone is a knot), the answer is cached in the database, and the photo
is downloaded once and served by Shelf, so browsers never contact Wikipedia themselves.

One request asks for the name and its usual disambiguations at once ("Muse", "Muse (band)",
"Muse (musician)"...), following Wikipedia's own redirects ("P!nk" is "Pink (singer)", "Ke$ha"
is "Kesha"); a search is the one fallback. Wikipedia turns away clients that ask too often or
don't say who they are, so the user agent names the project, and a refusal waits a while.
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

from . import __version__

UA = f"Shelf/{__version__} (self-hosted music server; https://github.com/Spinjitsudoom/shelf)"
LOOKUP = 2  # how artists are looked up: older misses and photo-less answers are retried
API = "https://en.wikipedia.org"
RETRY_MISS_AFTER = 30 * 86400
REFRESH_AFTER = 90 * 86400
OFFLINE_BACKOFF = 300
# Who someone is in music. The page's opening may say only this ("…is an English rock band").
_ROLE = (r"band|singer|musician|rapper|songwriter|group|duo|trio|dj|producer|composer|guitarist|vocalist|"
         r"drummer|pianist|bassist|keyboardist|violinist|cellist|saxophonist|trumpeter|orchestra|choir|ensemble|"
         r"quartet|quintet|recording artist|emcee|lyricist|supergroup")
_MUSIC_ROLE = re.compile(rf"\b({_ROLE})\b", re.I)
# The short description can also just name the music ("Reggae", "Jamaican ska"): genre words count
# there, but not in the text, where "soul" and "rock" mean other things too.
_MUSIC = re.compile(rf"\b({_ROLE}|music|musical|rock|metal|pop|punk|hip hop|rap|jazz|country|electronic|"
                    r"soundtrack|reggae|blues|soul|folk|r&b|edm|techno|k-pop|j-pop)\b", re.I)
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


_SUFFIXES = ("", " (band)", " (musician)", " (singer)", " (rapper)", " (group)", " (DJ)", " (producer)")
_PROPS = {"format": "json", "formatversion": 2, "redirects": 1, "prop": "extracts|pageimages|description|pageprops|info",
          "inprop": "url", "exintro": 1, "explaintext": 1, "exsentences": 6, "piprop": "thumbnail|original",
          "pithumbsize": 1200, "ppprop": "disambiguation|wikibase_item"}


def _query(**params) -> dict:
    return (_get_json(f"{API}/w/api.php?" + urllib.parse.urlencode({"action": "query", **_PROPS, **params})) or {}).get("query") or {}


def _page(p: dict) -> dict:
    """A page from the query API, shaped like the REST summary the rest of Shelf reads."""
    return {"type": "disambiguation" if "disambiguation" in (p.get("pageprops") or {}) else "standard",
            "title": p.get("title", ""), "description": p.get("description") or "", "extract": p.get("extract") or "",
            "thumbnail": p.get("thumbnail"), "originalimage": p.get("original"),
            "content_urls": {"desktop": {"page": p.get("fullurl")}}, "wikidata": (p.get("pageprops") or {}).get("wikibase_item")}


def _wikidata_photo(item: str | None) -> str | None:
    """The photo Wikidata has for someone, for pages that show none of their own."""
    if not item or not re.fullmatch(r"Q\d+", item):
        return None
    claims = (_get_json("https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode(
        {"action": "wbgetclaims", "entity": item, "property": "P18", "format": "json"})) or {}).get("claims") or {}
    for c in claims.get("P18") or []:
        name = ((c.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if isinstance(name, str) and name:
            return "https://commons.wikimedia.org/wiki/Special:FilePath/" + urllib.parse.quote(name.replace(" ", "_")) + "?width=1200"
    return None


def _is_artist_page(page: dict | None, name: str, redirected: bool = False) -> bool:
    """A musician's or band's page, under the artist's name (or one Wikipedia redirects it to)."""
    if not page or page.get("type") != "standard":
        return False
    title = re.sub(r"\s*\([^)]*\)$", "", page.get("title", ""))
    if fold(title) != fold(name) and not redirected:
        return False
    return bool(_MUSIC.search(page.get("description") or "") or _MUSIC_ROLE.search((page.get("extract") or "")[:300]))


def _find_page(name: str) -> dict | None:
    wanted = [name + s for s in _SUFFIXES]
    q = _query(titles="|".join(wanted))
    # Follow each guess to the page it lands on: spelling fixes, then redirects.
    moved = {n["from"]: n["to"] for n in q.get("normalized") or []}
    hops = {r["from"]: r["to"] for r in q.get("redirects") or []}
    pages = {p.get("title"): p for p in q.get("pages") or [] if not p.get("missing") and not p.get("invalid")}
    for guess in wanted:
        title = moved.get(guess, guess)
        target = hops.get(title, title)
        if target in pages and _is_artist_page(_page(pages[target]), name, redirected=target != title):
            return _page(pages[target])
    found = _query(generator="search", gsrlimit=5, gsrsearch=f'"{name}" band OR singer OR musician OR rapper')
    for p in sorted(found.get("pages") or [], key=lambda p: p.get("index", 99)):
        if _is_artist_page(_page(p), name):
            return _page(p)
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
    """(when it was fetched, what was found or None)."""
    at, data = _cached(db_path, key, kind)
    return at, (None if isinstance(data, dict) and data.get("miss") else data)


def _cached(db_path: Path, key: str, kind: str):
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
    at, data = _cached(db_path, key, "about")
    age = time.time() - at if at else None
    current = (data or {}).get("lookup", 0) >= LOOKUP if at else False
    if data and data.get("miss"):
        data = None
    # A miss, or an answer without a photo, from before the lookup got better is looked up again.
    if age is not None and current and (age < (REFRESH_AFTER if data else RETRY_MISS_AFTER)):
        return data
    # An older answer with a photo is kept while it still passes today's check of being a musician.
    if (age is not None and not current and data and data.get("hasImage") and age < REFRESH_AFTER
            and _is_artist_page({**data, "type": "standard"}, name, redirected=True)):
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
        store(db_path, key, "about", {"miss": True, "lookup": LOOKUP})
        return None
    # The thumbnail first: it's always a photo format (the original can be an SVG logo).
    has_image = False
    photos = [x.get("source") for x in (page.get("thumbnail"), page.get("originalimage")) if x]
    if not photos:
        try:
            photos = [p for p in [_wikidata_photo(page.get("wikidata"))] if p]
        except (OSError, ValueError) as e:
            log.info("Wikidata unavailable (%s)", e)
    for img in dict.fromkeys(photos):
        try:
            has_image = _save_image(img, image_path(data_dir, name))
            break
        except Exception as e:
            log.info("Couldn't fetch the photo of %s: %s", name, e)
    data = {
        "name": name,
        "title": page.get("title"),
        "description": page.get("description") or "",
        "extract": page.get("extract") or "",
        "url": ((page.get("content_urls") or {}).get("desktop") or {}).get("page"),
        "hasImage": has_image,
        "lookup": LOOKUP,
    }
    store(db_path, key, "about", data)
    return data
