"""Podcasts: follow shows by their RSS feed (Podbean, Apple Podcasts, anywhere that publishes one)
and play their episodes in the ordinary player.

Shows are found by typing a name (Apple's free podcast directory answers; only what's typed is
sent) or by pasting a link: the feed itself, a show's Podbean page, an Apple Podcasts page, or
any web page that links its feed. Each feed is stored once on the server, however many people
follow it, and checked every couple of hours while someone does.

An episode plays as a track with an id of its own range (EP_BASE + its id), so the queue, Connect,
the lock screen, downloads and places-kept all work on it unchanged; the server streams it from
the show's host. A show's artwork is served as an album cover in the same way (SHOW_BASE + id).
Episodes never count as plays: they stay out of stats, mixes and recommendations.
"""

from __future__ import annotations

import email.utils
import hashlib
import html
import ipaddress
import json
import logging
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from .db import session

log = logging.getLogger("shelf.podcasts")

EP_BASE = 1_000_000_000
SHOW_BASE = 1_000_000_000
AGENT = "Shelf/1.0 (self-hosted music server; podcasts)"
FEED_LIMIT = 30 * 1024 * 1024
ART_LIMIT = 10 * 1024 * 1024
CHECK_EVERY = 2 * 3600
MAX_EPISODES = 1000
ITUNES = "http://www.itunes.com/dtds/podcast-1.0.dtd"
CONTENT = "http://purl.org/rss/1.0/modules/content/"
ATOM = "http://www.w3.org/2005/Atom"
AUDIO_EXT = re.compile(r"\.(mp3|m4a|aac|mp4|ogg|oga|opus|wav|flac)(\?|$)", re.I)


class FeedError(Exception):
    """Something to tell the person: the link isn't a podcast, the host didn't answer..."""


def is_episode(track_id: int) -> bool:
    return track_id >= EP_BASE


def is_show(album_id: int) -> bool:
    return album_id >= SHOW_BASE


# ---------- fetching, only from the public internet ----------

def _public(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError):
        return False
    return bool(infos) and all(ipaddress.ip_address(i[4][0].split("%")[0]).is_global for i in infos)


def check_url(url: str) -> str:
    """The link, if it's http(s) on the public internet: a feed can't make the server reach
    into the home network."""
    p = urllib.parse.urlsplit(url.strip())
    if p.scheme not in ("http", "https") or not p.hostname:
        raise FeedError("That isn’t a web link.")
    if not _public(p.hostname):
        raise FeedError("Shelf only follows podcasts on the public internet.")
    return url.strip()


class _Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_Redirects())


def open_url(url: str, headers: dict | None = None, timeout: float = 20):
    req = urllib.request.Request(check_url(url), headers={"User-Agent": AGENT, **(headers or {})})
    return _opener.open(req, timeout=timeout)


def _read(url: str, limit: int, headers: dict | None = None, timeout: float = 20) -> tuple[bytes, object]:
    with open_url(url, headers, timeout) as r:
        data = r.read(limit + 1)
        if len(data) > limit:
            raise FeedError("That feed is too big.")
        return data, r


# ---------- reading a feed ----------

def _text(el, path: str, ns: dict | None = None) -> str:
    found = el.find(path, ns or {})
    return (found.text or "").strip() if found is not None and found.text else ""


def plain(text: str, limit: int = 4000) -> str:
    """Show notes as plain text: tags out, paragraphs kept."""
    text = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>", "\n", text or "")
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n\s*(\n\s*)+", "\n\n", text).strip()
    return text[:limit]


def duration(value: str) -> float | None:
    """itunes:duration: "1:02:03", "62:03" or seconds."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        parts = [float(p) for p in value.split(":")]
    except ValueError:
        return None
    secs = 0.0
    for p in parts:
        secs = secs * 60 + p
    return secs if 0 < secs < 7 * 86400 else None


def _date(value: str) -> float | None:
    try:
        return email.utils.parsedate_to_datetime(value).timestamp() if value else None
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def parse(data: bytes) -> dict:
    """An RSS podcast feed: the show and its audio episodes, newest first."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        raise FeedError("That link isn’t a podcast feed.")
    channel = root.find("channel")
    if channel is None:
        raise FeedError("That link isn’t a podcast feed.")
    ns = {"itunes": ITUNES, "content": CONTENT}
    image = channel.find("itunes:image", ns)
    art = (image.get("href") if image is not None else "") or _text(channel, "image/url")
    show = {
        "title": _text(channel, "title") or "Untitled podcast",
        "author": _text(channel, "itunes:author", ns) or _text(channel, "managingEditor"),
        "description": plain(_text(channel, "itunes:summary", ns) or _text(channel, "description"), 3000),
        "image": art.strip() or None,
        "link": _text(channel, "link") or None,
        "episodes": [],
    }
    for item in channel.findall("item"):
        enc = item.find("enclosure")
        url = (enc.get("url") or "").strip() if enc is not None else ""
        mime = (enc.get("type") or "").strip().lower() if enc is not None else ""
        if not url or not (mime.startswith("audio/") or (not mime and AUDIO_EXT.search(url))):
            continue  # video and text-only items aren't playable here
        ep_image = item.find("itunes:image", ns)
        try:
            size = int(enc.get("length") or 0) or None
        except ValueError:
            size = None
        show["episodes"].append({
            "guid": _text(item, "guid") or url,
            "title": _text(item, "title") or "Untitled episode",
            "description": plain(_text(item, "content:encoded", ns) or _text(item, "description")
                                 or _text(item, "itunes:summary", ns)),
            "audio_url": url,
            "mime": mime or "audio/mpeg",
            "size": size,
            "duration": duration(_text(item, "itunes:duration", ns)),
            "published": _date(_text(item, "pubDate")),
            "image": (ep_image.get("href") if ep_image is not None else None) or None,
        })
    show["episodes"].sort(key=lambda e: -(e["published"] or 0))
    show["episodes"] = show["episodes"][:MAX_EPISODES]
    if not show["episodes"]:
        raise FeedError("That feed has no episodes to listen to.")
    return show


# ---------- finding a show's feed ----------

def _itunes(path: str, **params) -> dict:
    q = urllib.parse.urlencode(params)
    data, _ = _read(f"https://itunes.apple.com/{path}?{q}", 2 * 1024 * 1024)
    return json.loads(data)


def search(term: str) -> list[dict]:
    """Shows matching a name, from Apple's podcast directory."""
    r = _itunes("search", media="podcast", entity="podcast", term=term.strip(), limit=20)
    return [{"title": x.get("collectionName") or x.get("trackName") or "", "author": x.get("artistName") or "",
             "feedUrl": x["feedUrl"], "image": x.get("artworkUrl600") or x.get("artworkUrl100")}
            for x in r.get("results", []) if x.get("feedUrl")]


def feed_for(link: str) -> str:
    """The feed behind a pasted link: a feed already, a Podbean show page, an Apple Podcasts
    page, or any page that names its feed."""
    link = link.strip()
    p = urllib.parse.urlsplit(link)
    host = (p.hostname or "").lower()
    if host.endswith(".podbean.com") and host not in ("www.podbean.com", "feed.podbean.com"):
        return f"https://feed.podbean.com/{host.split('.')[0]}/feed.xml"
    if host == "podcasts.apple.com":
        found = re.search(r"/id(\d+)", p.path)
        if not found:
            raise FeedError("That Apple Podcasts link doesn’t name a show.")
        hits = _itunes("lookup", id=found.group(1), entity="podcast").get("results", [])
        if not hits or not hits[0].get("feedUrl"):
            raise FeedError("Apple doesn’t share that show’s feed.")
        return hits[0]["feedUrl"]
    data, _ = _read(link, FEED_LIMIT)
    head = data[:4096].lstrip().lower()
    if head.startswith(b"<?xml") or b"<rss" in head:
        return link
    page = data.decode("utf-8", "replace")
    for tag in re.findall(r"<link\b[^>]*>", page, re.I):
        if re.search(r"type=[\"']application/(rss|atom)\+xml", tag, re.I):
            href = re.search(r"href=[\"']([^\"']+)", tag, re.I)
            if href:
                return urllib.parse.urljoin(link, html.unescape(href.group(1)))
    raise FeedError("Couldn’t find a podcast feed on that page.")


def looks_like_link(text: str) -> bool:
    return bool(re.match(r"(?i)^(https?://\S+|[\w-]+(\.[\w-]+)*\.[a-z]{2,}(/\S*)?)$", text.strip()))


# ---------- storing ----------

def store(conn, feed_url: str, show: dict, now: float | None = None) -> int:
    now = now or time.time()
    row = conn.execute("SELECT id FROM podcasts WHERE feed_url = ?", (feed_url,)).fetchone()
    fields = (show["title"], show["author"], show["description"], show["image"], show["link"], now)
    if row:
        pid = row["id"]
        conn.execute("""UPDATE podcasts SET title = ?, author = ?, description = ?, image_url = ?, link = ?,
                        checked_at = ?, error = NULL WHERE id = ?""", (*fields, pid))
    else:
        pid = conn.execute("""INSERT INTO podcasts(title, author, description, image_url, link, checked_at, feed_url, added_at)
                              VALUES(?, ?, ?, ?, ?, ?, ?, ?)""", (*fields, feed_url, now)).lastrowid
    for e in show["episodes"]:
        conn.execute(
            """INSERT INTO episodes(podcast_id, guid, title, description, audio_url, mime, size, duration, published_at, image_url)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(podcast_id, guid) DO UPDATE SET title = excluded.title, description = excluded.description,
                 audio_url = excluded.audio_url, mime = excluded.mime, size = excluded.size,
                 duration = COALESCE(excluded.duration, episodes.duration), published_at = excluded.published_at,
                 image_url = excluded.image_url""",
            (pid, e["guid"], e["title"], e["description"], e["audio_url"], e["mime"], e["size"], e["duration"],
             e["published"] or now, e["image"]))
    return pid


def fetch_show(feed_url: str) -> dict:
    data, _ = _read(feed_url, FEED_LIMIT)
    return parse(data)


def follow(conn, user_id: int, pid: int, now: float | None = None) -> None:
    conn.execute("INSERT OR IGNORE INTO podcast_subs(user_id, podcast_id, subscribed_at) VALUES(?, ?, ?)",
                 (user_id, pid, now or time.time()))


def unfollow(conn, user_id: int, pid: int) -> None:
    conn.execute("DELETE FROM podcast_subs WHERE user_id = ? AND podcast_id = ?", (user_id, pid))
    # Nobody follows it any more: the show and what people kept of it go.
    if not conn.execute("SELECT 1 FROM podcast_subs WHERE podcast_id = ?", (pid,)).fetchone():
        conn.execute("DELETE FROM podcasts WHERE id = ?", (pid,))


def following(conn, user_id: int) -> set[int]:
    return {r[0] for r in conn.execute("SELECT podcast_id FROM podcast_subs WHERE user_id = ?", (user_id,))}


# ---------- playing ----------

def cover_version(show) -> str | None:
    return hashlib.sha1(show["image_url"].encode()).hexdigest()[:10] if show["image_url"] else None


def codec(mime: str) -> str:
    return {"audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/mp4": "aac", "audio/x-m4a": "aac", "audio/aac": "aac",
            "audio/ogg": "vorbis", "audio/opus": "opus", "audio/wav": "pcm", "audio/flac": "flac"}.get(mime, "mp3")


def episode_json(e, show, state=None) -> dict:
    """An episode as the players see a track, plus what's only an episode's."""
    return {
        "id": EP_BASE + e["id"], "kind": "episode", "episodeId": e["id"], "podcastId": show["id"],
        "title": e["title"], "artist": show["title"], "artists": [show["title"]],
        "album": show["title"], "albumId": SHOW_BASE + show["id"], "albumArtist": show["title"], "albumArtists": [show["title"]],
        "cover": cover_version(show), "trackNo": None, "discNo": None,
        "duration": round(e["duration"] or 0, 2), "codec": codec(e["mime"]), "mime": e["mime"],
        "bitrate": None, "sampleRate": None, "bits": None, "lufs": None, "peak": None, "bpm": None,
        "key": None, "camelot": None, "mix": None,
        "published": e["published_at"], "description": e["description"] or "",
        "position": state["position"] if state else 0, "finished": bool(state["finished"]) if state else False,
    }


def show_json(show, episodes: int = 0, unplayed: int = 0, latest: float | None = None, following_it: bool = True) -> dict:
    return {"id": show["id"], "title": show["title"], "author": show["author"] or "", "description": show["description"] or "",
            "link": show["link"], "feedUrl": show["feed_url"], "albumId": SHOW_BASE + show["id"], "cover": cover_version(show),
            "episodes": episodes, "unplayed": unplayed, "latest": latest, "following": following_it,
            "checkedAt": show["checked_at"], "error": show["error"]}


def episode(conn, track_id: int):
    """(episode row, show row) for an episode's track id, or None."""
    e = conn.execute("SELECT * FROM episodes WHERE id = ?", (track_id - EP_BASE,)).fetchone()
    if not e:
        return None
    return e, conn.execute("SELECT * FROM podcasts WHERE id = ?", (e["podcast_id"],)).fetchone()


def state(conn, user_id: int, episode_id: int):
    return conn.execute("SELECT position, finished FROM episode_state WHERE user_id = ? AND episode_id = ?",
                        (user_id, episode_id)).fetchone()


START = 10.0
END = 30.0


def keep_place(conn, user_id: int, episode_id: int, position: float, length: float, now: float | None = None) -> None:
    """Where someone is in an episode. Near the end counts as finished; near the start, not begun."""
    finished = bool(length) and position > length - END
    pos = 0.0 if finished or position < START else float(position)
    if not finished and not pos:
        # Back at the start: forget the place, but don't unmark an episode marked finished.
        conn.execute("UPDATE episode_state SET position = 0, updated_at = ? WHERE user_id = ? AND episode_id = ?",
                     (now or time.time(), user_id, episode_id))
        return
    conn.execute(
        """INSERT INTO episode_state(user_id, episode_id, position, finished, updated_at) VALUES(?, ?, ?, ?, ?)
           ON CONFLICT(user_id, episode_id) DO UPDATE SET position = excluded.position,
             finished = MAX(episode_state.finished, excluded.finished), updated_at = excluded.updated_at""",
        (user_id, episode_id, pos, int(finished), now or time.time()))


def mark(conn, user_id: int, episode_id: int, finished: bool, now: float | None = None) -> None:
    conn.execute(
        """INSERT INTO episode_state(user_id, episode_id, position, finished, updated_at) VALUES(?, ?, 0, ?, ?)
           ON CONFLICT(user_id, episode_id) DO UPDATE SET position = 0, finished = excluded.finished,
             updated_at = excluded.updated_at""",
        (user_id, episode_id, int(finished), now or time.time()))


# ---------- artwork ----------

def art_path(data_dir: Path, show) -> Path | None:
    """The show's artwork, downloaded once (again when the feed changes it)."""
    if not show["image_url"]:
        return None
    folder = data_dir / "podcast-art"
    path = folder / f"{show['id']}-{cover_version(show)}.img"
    if path.is_file():
        return path
    try:
        data, _ = _read(show["image_url"], ART_LIMIT, timeout=15)
    except (OSError, FeedError, ValueError) as e:
        log.info("No artwork for %s: %s", show["title"], e)
        return None
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob(f"{show['id']}-*.img"):
        old.unlink(missing_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    return path


# ---------- keeping shows up to date ----------

def refresh(db_path: Path, pid: int) -> int:
    """Read one show's feed again; returns how many episodes are new."""
    with session(db_path) as conn:
        row = conn.execute("SELECT feed_url FROM podcasts WHERE id = ?", (pid,)).fetchone()
        if not row:
            return 0
        before = conn.execute("SELECT COUNT(*) FROM episodes WHERE podcast_id = ?", (pid,)).fetchone()[0]
    try:
        show = fetch_show(row["feed_url"])
    except (OSError, FeedError, ValueError) as e:
        with session(db_path) as conn:
            conn.execute("UPDATE podcasts SET checked_at = ?, error = ? WHERE id = ?", (time.time(), str(e)[:300], pid))
        log.info("Podcast %s: %s", row["feed_url"], e)
        return 0
    with session(db_path) as conn:
        store(conn, row["feed_url"], show)
        return conn.execute("SELECT COUNT(*) FROM episodes WHERE podcast_id = ?", (pid,)).fetchone()[0] - before


class Refresher:
    """Checks the shows people follow every couple of hours."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._stop = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._loop, name="shelf-podcasts", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        self._stop.wait(90)
        while not self._stop.is_set():
            with session(self.db_path) as conn:
                due = [r[0] for r in conn.execute(
                    """SELECT p.id FROM podcasts p WHERE EXISTS (SELECT 1 FROM podcast_subs s WHERE s.podcast_id = p.id)
                       AND COALESCE(p.checked_at, 0) < ?""", (time.time() - CHECK_EVERY,))]
            for pid in due:
                if self._stop.is_set():
                    return
                try:
                    refresh(self.db_path, pid)
                except Exception:
                    log.exception("Checking podcast %s failed", pid)
            self._stop.wait(600)
