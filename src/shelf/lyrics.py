"""Lyrics for a track, from the best source available.

In order of preference:
  1. timed lyrics from the music folder: a ``.lrc`` file next to the song, or timed tags
  2. timed lyrics from LRCLIB (lrclib.net), a free public lyrics database
  3. plain lyrics from the file's tags
  4. plain lyrics from LRCLIB

LRCLIB answers (including "not found") are cached in the database so each song is
looked up once. Only the artist, title, album and length are sent.
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

from .db import session
from .tags import embedded_lyrics

log = logging.getLogger("shelf.lyrics")

LRCLIB = "https://lrclib.net/api"
USER_AGENT = "Shelf/0.4 (self-hosted music server)"
RETRY_MISS_AFTER = 14 * 86400  # look again for songs LRCLIB didn't have, after two weeks
OFFLINE_BACKOFF = 300  # after a network error, don't try LRCLIB again for five minutes

_TIME = re.compile(r"\[(\d+):(\d{1,2}(?:[.:]\d{1,3})?)\]")
_OFFSET = re.compile(r"^\[offset:\s*([+-]?\d+)\]", re.I | re.M)
_TAG_LINE = re.compile(r"^\[[a-z]+:.*\]$", re.I)

_offline_until = 0.0
_inflight: dict[str, threading.Event] = {}
_inflight_lock = threading.Lock()


def parse_lrc(text: str) -> list[dict] | None:
    """LRC text to [{t: seconds, text}], sorted. None if it has no timestamps."""
    m = _OFFSET.search(text)
    offset = int(m.group(1)) / 1000 if m else 0.0
    lines = []
    for raw in text.splitlines():
        stamps = list(_TIME.finditer(raw))
        if not stamps:
            continue
        words = _TIME.sub("", raw)
        words = re.sub(r"<\d+:\d+(?:\.\d+)?>", "", words).strip()  # word-level timing marks
        for s in stamps:
            secs = int(s.group(1)) * 60 + float(s.group(2).replace(":", "."))
            lines.append({"t": round(max(0.0, secs - offset), 2), "text": words})
    if not lines:
        return None
    lines.sort(key=lambda l: l["t"])
    return lines


def _plain(text: str) -> str:
    """Plain lyrics, with any stray LRC tags and timestamps removed."""
    out = [_TIME.sub("", line).rstrip() for line in text.splitlines() if not _TAG_LINE.match(line.strip())]
    return "\n".join(out).strip()


def _local(path: Path) -> tuple[list[dict] | None, str | None]:
    """(timed lines, plain text) from the music folder."""
    for lrc in (path.with_suffix(".lrc"), path.with_suffix(".LRC")):
        try:
            if lrc.is_file():
                text = lrc.read_text(encoding="utf-8-sig", errors="replace")
                synced = parse_lrc(text)
                return synced, None if synced else _plain(text)
        except OSError:
            pass
    text = embedded_lyrics(path)
    if not text or not text.strip():
        return None, None
    synced = parse_lrc(text)
    return synced, None if synced else _plain(text)


def _key(artist: str, title: str, album: str, duration: float) -> str:
    return "\x1f".join([artist.casefold().strip(), title.casefold().strip(), album.casefold().strip(), str(round(duration))])


def _fetch_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as res:
            return json.load(res)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def _lrclib(artist: str, title: str, album: str, duration: float) -> dict | None:
    """Best LRCLIB match, or None. Raises on network errors."""
    params = {"artist_name": artist, "track_name": title}
    exact = dict(params, album_name=album, duration=str(round(duration)))
    hit = _fetch_json(f"{LRCLIB}/get?{urllib.parse.urlencode(exact)}")
    if hit and (hit.get("syncedLyrics") or hit.get("instrumental")):
        return hit
    # Same song released on another album or edition: search, matching the length.
    results = _fetch_json(f"{LRCLIB}/search?{urllib.parse.urlencode(params)}") or []
    close = [r for r in results if r.get("duration") and abs(r["duration"] - duration) <= 3]
    close.sort(key=lambda r: (not r.get("syncedLyrics"), not r.get("plainLyrics"), abs(r["duration"] - duration)))
    return close[0] if close else hit


def _online(db_path: Path, artist: str, title: str, album: str, duration: float) -> dict | None:
    """Cached LRCLIB result as {synced, plain, instrumental}, or None if unknown/unavailable."""
    global _offline_until
    key = _key(artist, title, album, duration)
    with session(db_path) as conn:
        row = conn.execute("SELECT * FROM lyrics_cache WHERE key = ?", (key,)).fetchone()
    if row and (row["found"] or time.time() - row["fetched_at"] < RETRY_MISS_AFTER):
        return dict(row) if row["found"] else None
    if time.time() < _offline_until:
        return None

    # One lookup per song at a time, even if several devices ask at once.
    with _inflight_lock:
        ev = _inflight.get(key)
        mine = ev is None
        if mine:
            ev = _inflight[key] = threading.Event()
    if not mine:
        ev.wait(timeout=10)
        with session(db_path) as conn:
            row = conn.execute("SELECT * FROM lyrics_cache WHERE key = ?", (key,)).fetchone()
        return dict(row) if row and row["found"] else None

    try:
        try:
            hit = _lrclib(artist, title, album, duration)
        except (OSError, ValueError) as e:
            _offline_until = time.time() + OFFLINE_BACKOFF
            log.info("LRCLIB unavailable (%s); using lyrics from files only for now", e)
            return None
        found = bool(hit and (hit.get("syncedLyrics") or hit.get("plainLyrics") or hit.get("instrumental")))
        result = {
            "found": int(found),
            "synced": (hit or {}).get("syncedLyrics") or None,
            "plain": (hit or {}).get("plainLyrics") or None,
            "instrumental": int(bool((hit or {}).get("instrumental"))),
        }
        with session(db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO lyrics_cache(key, fetched_at, found, synced, plain, instrumental)"
                " VALUES(?, ?, ?, ?, ?, ?)",
                (key, time.time(), result["found"], result["synced"], result["plain"], result["instrumental"]),
            )
        return result if found else None
    finally:
        with _inflight_lock:
            _inflight.pop(key, None)
        ev.set()


def lyrics_for(db_path: Path, row, online: bool) -> dict:
    """{kind: synced|plain|instrumental|none, lines?, text?, source} for a track row."""
    synced, plain = _local(Path(row["path"]))
    if synced:
        return {"kind": "synced", "lines": synced, "source": "file"}

    hit = _online(db_path, row["artist"], row["title"], row["album"], row["duration"] or 0) if online else None
    if hit and hit.get("synced"):
        lines = parse_lrc(hit["synced"])
        if lines:
            return {"kind": "synced", "lines": lines, "source": "lrclib"}
    if plain:
        return {"kind": "plain", "text": plain, "source": "file"}
    if hit and hit.get("plain"):
        return {"kind": "plain", "text": _plain(hit["plain"]), "source": "lrclib"}
    if hit and hit.get("instrumental"):
        return {"kind": "instrumental", "source": "lrclib"}
    return {"kind": "none", "source": None, "searchedOnline": online}
