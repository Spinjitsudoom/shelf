"""Music videos: find a song's official video on YouTube, to play in YouTube's own player.

yt-dlp runs a YouTube search ("artist title official music video") without downloading
anything, and the results are scored so the artist's own upload wins over lyric videos,
covers, live versions and fan uploads. Answers (including "no video") are cached in the
database, so each song is looked up once.
"""

from __future__ import annotations

import logging
import math
import re
import threading
import time
import unicodedata
from functools import lru_cache
from pathlib import Path

from .db import session

log = logging.getLogger("shelf.videos")

RETRY_MISS_AFTER = 30 * 86400
OFFLINE_BACKOFF = 300
RESULTS = 8

_BAD = re.compile(
    r"\b(lyrics?|lyric video|visuali[sz]er|audio|cover|reaction|karaoke|instrumental|8d|slowed|sped up|"
    r"nightcore|remix|tutorial|lesson|teaser|trailer|behind the scenes|making of|fan made|fanmade|amv|edit)\b",
    re.I,
)
_LIVE = re.compile(r"\b(live|concert|session|acoustic|unplugged)\b", re.I)
_OFFICIAL = re.compile(r"\bofficial (music )?video\b|\bmusic video\b", re.I)
_TITLE_NOISE = re.compile(r"\s*[\(\[][^)\]]*(feat|ft\.|with|remaster|version|edit|mix|explicit|clean|bonus)[^)\]]*[\)\]]", re.I)

_offline_until = 0.0
_inflight: dict[str, threading.Event] = {}
_lock = threading.Lock()


@lru_cache(maxsize=262144)  # the same names are folded over and over (every song, every mix)
def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s.casefold()).strip()


def _key(artist: str, title: str) -> str:
    return f"{fold(artist)}\x1f{fold(title)}"


def score(entry: dict, artist: str, title: str, duration: float) -> float | None:
    """How likely a search result is this song's official video; None if it clearly isn't."""
    vt = entry.get("title") or ""
    channel = entry.get("channel") or entry.get("uploader") or ""
    fv, fc, fa = fold(vt), fold(channel), fold(artist)
    ft = fold(_TITLE_NOISE.sub("", title)) or fold(title)
    if not ft or ft not in fv:
        return None
    artist_in_title = fa and fa in fv
    artist_channel = fa and (fa.replace(" ", "") in fc.replace(" ", "") or fc.replace(" ", "") in fa.replace(" ", ""))
    if not (artist_in_title or artist_channel):
        return None
    if fc.endswith(" topic"):
        return None  # "Provided to YouTube" uploads: just the cover art, not a video
    s = 0.0
    if artist_channel:
        s += 4
    if "vevo" in fc:
        s += 3
    if _OFFICIAL.search(vt):
        s += 3
    if not artist_in_title:
        s -= 2
    bad = _BAD.findall(vt)
    if bad and not any(fold(b) in ft for b in bad):
        s -= 6
    if _LIVE.search(vt) and not _LIVE.search(title):
        s -= 4
    vd = entry.get("duration")
    if vd and duration:
        diff = abs(vd - duration)
        if diff > 90 and (vd / duration > 1.6 or duration / vd > 1.6):
            s -= 3
    views = entry.get("view_count") or 0
    s += math.log10(views + 1) / 3  # a tiebreak: the real video is usually the most watched
    return s


def _search(artist: str, title: str) -> list[dict]:
    import yt_dlp  # imported lazily: it's slow to import and only needed for lookups

    opts = {"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True, "noplaylist": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{RESULTS}:{artist} {title} official music video", download=False)
    return [e for e in (info or {}).get("entries") or [] if e and e.get("id")]


def best_match(entries: list[dict], artist: str, title: str, duration: float) -> dict | None:
    scored = [(score(e, artist, title, duration), e) for e in entries]
    scored = [(s, e) for s, e in scored if s is not None and s >= 4]
    if not scored:
        return None
    return max(scored, key=lambda x: x[0])[1]


def video_for(db_path: Path, artist: str, title: str, duration: float) -> dict | None:
    """{videoId, title, channel} for a song's music video, or None."""
    global _offline_until
    key = _key(artist, title)
    with session(db_path) as conn:
        row = conn.execute("SELECT * FROM video_cache WHERE key = ?", (key,)).fetchone()
    if row and (row["video_id"] or time.time() - row["fetched_at"] < RETRY_MISS_AFTER):
        return {"videoId": row["video_id"], "title": row["title"], "channel": row["channel"]} if row["video_id"] else None
    if time.time() < _offline_until:
        return None

    with _lock:
        ev = _inflight.get(key)
        mine = ev is None
        if mine:
            ev = _inflight[key] = threading.Event()
    if not mine:
        ev.wait(timeout=20)
        return video_for(db_path, artist, title, duration) if key not in _inflight else None

    try:
        try:
            entries = _search(artist, title)
        except Exception as e:  # yt-dlp raises its own error types for network trouble
            _offline_until = time.time() + OFFLINE_BACKOFF
            log.info("YouTube search unavailable (%s); trying again later", str(e).splitlines()[0][:200])
            return None
        hit = best_match(entries, artist, title, duration)
        with session(db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO video_cache(key, fetched_at, video_id, title, channel) VALUES(?, ?, ?, ?, ?)",
                (key, time.time(), hit and hit["id"], hit and hit.get("title"),
                 hit and (hit.get("channel") or hit.get("uploader"))),
            )
        return {"videoId": hit["id"], "title": hit.get("title"), "channel": hit.get("channel") or hit.get("uploader")} if hit else None
    finally:
        with _lock:
            _inflight.pop(key, None)
        ev.set()


_CLEAN = re.compile(r"\s*[\(\[][^)\]]*(official|video|audio|hd|4k|remaster|explicit|clean)[^)\]]*[\)\]]", re.I)


def clean_title(title: str, artist: str) -> str:
    """'Måneskin - CHOSEN (Official Video)' -> 'CHOSEN'."""
    t = _CLEAN.sub("", title or "").strip()
    parts = re.split(r"\s+[-–—|]\s+", t, maxsplit=1)
    if len(parts) == 2 and fold(artist) in fold(parts[0]):
        t = parts[1]
    return t.strip(" -–—|") or title


def artist_videos(db_path: Path, artist: str, limit: int = 8) -> list[dict]:
    """The artist's own music videos (other than live, lyric and fan uploads), cached."""
    global _offline_until
    from . import artists  # the shared artist cache table

    key = fold(artist)
    at, data = artists.cached(db_path, key, "videos")
    if at and time.time() - at < (14 * 86400 if data else RETRY_MISS_AFTER):
        return data or []
    if time.time() < _offline_until:
        return data or []
    try:
        import yt_dlp

        opts = {"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True, "noplaylist": True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch20:{artist} official music video", download=False)
        entries = [e for e in (info or {}).get("entries") or [] if e and e.get("id")]
    except Exception as e:
        _offline_until = time.time() + OFFLINE_BACKOFF
        log.info("YouTube search unavailable (%s)", str(e).splitlines()[0][:200])
        return data or []

    fa = fold(artist).replace(" ", "")
    out, seen = [], set()
    for e in entries:
        vt = e.get("title") or ""
        fc = fold(e.get("channel") or e.get("uploader") or "").replace(" ", "")
        own = fa and (fa in fc or (fc and fc in fa))
        if not own and not ("vevo" in fc and fold(artist) in fold(vt)):
            continue
        if fc.endswith("topic") or _BAD.search(vt) or _LIVE.search(vt):
            continue
        if not _OFFICIAL.search(vt) and fold(artist) not in fold(vt):
            continue
        name = clean_title(vt, artist)
        if fold(name) in seen:
            continue
        seen.add(fold(name))
        out.append({"videoId": e["id"], "title": name, "artist": artist, "duration": e.get("duration")})
        if len(out) >= limit:
            break
    artists.store(db_path, key, "videos", out or None)
    return out
