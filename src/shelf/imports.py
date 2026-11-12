"""Importing playlists from elsewhere, matched against the library.

Where they come from:
- a Spotify playlist or album link (its public embed page lists the songs; up to 100);
- a YouTube or YouTube Music playlist link (its page lists the first 100 videos);
- a playlist file from another player: M3U/M3U8, PLS, XSPF;
- a CSV export (Exportify, TuneMyMusic, Soundiiz and the like);
- Spotify's own data download (Playlist1.json, YourLibrary.json);
- a pasted list of songs, one per line ("Artist - Title", "Title by Artist", in either order).

Each song becomes a "want": artist, title, album, duration, plus `text` (a line of free text such
as a video title, when artist and title aren't known apart) and `path` (a file path from another
player). Library.find() looks each one up: a file path that ends the same way as one in the
library; then the same title by the same artist (spelling, accents, "feat." and "Remastered" set
aside); then, for free text, an artist and one of their song titles both appearing in it as whole
words. Songs that aren't in the library are reported, never guessed.
"""

from __future__ import annotations

import csv
import difflib
import io
import json
import re
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from urllib.parse import parse_qs, unquote, unquote_plus, urlsplit

MAX_SONGS = 5000  # as many as a playlist takes at once
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"

_SPLIT = re.compile(r"\s*[;,]\s*|\s+/\s+|\s+(?:&|and|x|×|vs\.?|with|feat\.?|ft\.?|featuring)\s+", re.I)
_BRACKETS = re.compile(r"\s*[\(\[\{][^\)\]\}]*[\)\]\}]")
_VERSION = re.compile(r"\s+[-–—]\s+[^-–—]*\b(?:remaster(?:ed)?|version|edit|live|mono|stereo|mix|remix|demo|acoustic|"
                      r"bonus|deluxe|radio|single|explicit|clean|from|feat|ft)\b.*$", re.I)
_FEAT = re.compile(r"\s+(?:feat\.?|ft\.?|featuring)\s+.*$", re.I)
_NUMBERING = re.compile(r"^\s*(?:\d{1,4}\s*[.)\]:-]+|[-*•]+)\s*")


def fold(s: str | None) -> str:
    """Lower case, accents off, punctuation to spaces: "Don't Stop Me Now" → "dont stop me now"."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).casefold()
    s = s.replace("&", " and ").replace("'", "").replace("’", "").replace("`", "")
    return re.sub(r"[\W_]+", " ", s).strip()


def core(title: str) -> str:
    """The song's name without what's around it: brackets, "feat. X", " - Remastered 2009"."""
    t = _VERSION.sub("", _BRACKETS.sub("", title or ""))
    t = _FEAT.sub("", t).strip()
    return t or (title or "")


def _artist_key(name: str) -> str:
    f = fold(name)
    return f[4:] if f.startswith("the ") else f


def artist_names(credit: str | None) -> set[str]:
    """"Peso Pluma & Anitta" → {"peso pluma and anitta", "peso pluma", "anitta"}."""
    if not credit:
        return set()
    out = {_artist_key(credit)} | {_artist_key(p) for p in _SPLIT.split(credit) if p and p.strip()}
    return {n for n in out if n}


_NOISE_WORDS = {"official", "oficial", "video", "audio", "lyric", "lyrics", "music", "visualizer", "visualiser",
                "hd", "hq", "4k", "remaster", "remastered", "by", "ft", "feat", "featuring", "topic", "vevo", "mv"}


def close(a: str, b: str) -> bool:
    """Folded titles that are the same song spelled a little differently: "basket case" and
    "basketcase", "hitchin a ride" and "hitching a ride"; not "nightmare" and "nightmare theme"."""
    if not a or not b:
        return False
    if a.replace(" ", "") == b.replace(" ", ""):
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.88


def want(artist="", title="", album="", duration=None, text="", path="") -> dict:
    return {"artist": (artist or "").strip(), "title": (title or "").strip(), "album": (album or "").strip(),
            "duration": duration, "text": (text or "").strip(), "path": (path or "").strip()}


def label(w: dict) -> str:
    """How a song is shown when it isn't in the library."""
    if w["artist"] and w["title"]:
        return f"{w['artist']} - {w['title']}"
    return w["title"] or w["text"] or w["path"].replace("\\", "/").rsplit("/", 1)[-1]


# ---------- the library ----------

def _path_tail(path: str, n: int) -> str:
    p = unquote(path.strip()).replace("\\", "/")
    if p.lower().startswith("file://"):
        p = p[7:]
    parts = [x for x in p.casefold().split("/") if x]
    return "/".join(parts[-n:]) if len(parts) >= n else ""


def _path_text(path: str) -> str:
    """Words from a file path: the file's name without its number, then its folders."""
    parts = [x for x in unquote(path).replace("\\", "/").split("/") if x]
    if not parts:
        return ""
    stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", parts[-1])
    stem = re.sub(r"^\s*\d{1,3}(?:[-.]\d{1,3})?\s*[-._)]*\s*", "", stem)
    return " ".join([stem, *parts[-3:-1]])


class Library:
    """The library's songs, indexed for looking up imported ones. `rows`: dicts or sqlite rows with
    id, title, artist, album_artist, album, duration, path."""

    def __init__(self, rows):
        self.songs: dict[int, dict] = {}
        self.by_title: dict[str, list[int]] = defaultdict(list)
        self.by_core: dict[str, list[int]] = defaultdict(list)
        self.by_artist: dict[str, list[int]] = defaultdict(list)
        self.by_first_word: dict[str, set[str]] = defaultdict(set)
        tails: dict[int, dict[str, list[int]]] = {3: defaultdict(list), 2: defaultdict(list)}
        for r in rows:
            r = dict(r)
            tid = r["id"]
            names = artist_names(r.get("artist")) | artist_names(r.get("album_artist"))
            full, short = fold(r["title"]), fold(core(r["title"]))
            self.songs[tid] = {"names": names, "title": full, "core": short, "album": fold(r.get("album")),
                               "duration": r.get("duration") or 0}
            if full:
                self.by_title[full].append(tid)
            if short:
                self.by_core[short].append(tid)
            for n in names:
                self.by_artist[n].append(tid)
                self.by_first_word[n.split(" ", 1)[0]].add(n)
            for n in (3, 2):
                tail = _path_tail(r.get("path") or "", n)
                if tail:
                    tails[n][tail].append(tid)
        self.tails = tails

    def _best(self, ids, w) -> int | None:
        """The closest in length (then on the same album) of songs that all fit."""
        if not ids:
            return None
        want_album = fold(w["album"])

        def score(tid):
            s = self.songs[tid]
            off = abs(w["duration"] - s["duration"]) if w["duration"] and s["duration"] else 0
            return (off, 0 if want_album and s["album"] == want_album else 1, tid)

        return min(dict.fromkeys(ids), key=score)

    def _by_path(self, path: str) -> int | None:
        for n in (3, 2):
            hits = self.tails[n].get(_path_tail(path, n)) or []
            if len(set(hits)) == 1:
                return hits[0]
        return None

    def _by_title(self, w: dict) -> int | None:
        names = artist_names(w["artist"])

        def fits(tid):
            return not names or bool(names & self.songs[tid]["names"])

        for index, key in ((self.by_title, fold(w["title"])), (self.by_core, fold(core(w["title"])))):
            ids = [t for t in index.get(key, []) if fits(t)]
            if ids and (names or len(set(ids)) == 1 or w["duration"]):
                return self._best(ids, w)
        if not names:
            return None
        # Close spellings among the artist's own songs ("Dont Stop Me Now!" and the like).
        want_core = fold(core(w["title"]))
        mine = {t for n in names for t in self.by_artist.get(n, [])}
        return self._best([t for t in mine if close(want_core, self.songs[t]["core"])], w)

    def _by_text(self, w: dict) -> int | None:
        line = f" {fold(' '.join([w['text'], w['artist'], w['title']]))} "
        words = set(line.split())
        # Each hit: how long the name that matched is, then whether it's the song's whole title (so
        # "Walk" is the song Walk, not "Walk (Live)", unless the text says "Live").
        found: list[tuple[tuple[int, int], int]] = []
        named: set[str] = set()
        for word in words:
            for name in self.by_first_word.get(word, ()):
                if f" {name} " not in line:
                    continue
                named.add(name)
                for tid in self.by_artist[name]:
                    s = self.songs[tid]
                    hit = max(((len(t), int(t == s["title"])) for t in (s["title"], s["core"]) if t and f" {t} " in line),
                              default=None)
                    if hit:
                        found.append((hit, tid))
        if found:
            best = max(h for h, _ in found)
            return self._best([t for h, t in found if h == best], w)
        # An artist named, but none of their titles spelled out: what's left of the text, once the
        # artist and the likes of "Official Video" are taken out, close to one of their titles.
        if named:
            rest = f" {fold(_BRACKETS.sub(' ', ' '.join([w['text'], w['title']])))} "
            for name in sorted(named, key=len, reverse=True):
                rest = rest.replace(f" {name} ", " ")
            rest = " ".join(x for x in rest.split() if x not in _NOISE_WORDS)
            near = [t for name in named for t in self.by_artist[name] if close(rest, self.songs[t]["core"])]
            if near:
                return self._best(near, w)
        # No artist named: only a song whose whole name is the text, and only one such song.
        alone = fold(core(w["text"] or w["title"]))
        ids = set(self.by_title.get(alone, [])) | set(self.by_core.get(alone, []))
        if len(ids) == 1:
            return ids.pop()
        if ids and w["duration"]:
            near = [t for t in ids if abs(self.songs[t]["duration"] - w["duration"]) <= 3]
            return near[0] if len(near) == 1 else None
        return None

    def find(self, w: dict) -> int | None:
        """The library's song for an imported one, or None."""
        if w["path"]:
            hit = self._by_path(w["path"])
            if hit:
                return hit
        if w["title"]:
            hit = self._by_title(w)
            if hit:
                return hit
        if w["text"] or w["artist"] or w["title"]:
            return self._by_text(w)
        if w["path"]:
            return self._by_text(want(text=_path_text(w["path"]), duration=w["duration"]))
        return None


# ---------- reading files ----------

def _name_from(filename: str) -> str:
    stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", filename.replace("\\", "/").rsplit("/", 1)[-1])
    return re.sub(r"[_]+", " ", stem).strip()


def _seconds(value, ms: bool = False) -> float | None:
    v = str(value or "").strip()
    if not v:
        return None
    if ":" in v:
        try:
            total = 0.0
            for part in v.split(":"):
                total = total * 60 + float(part)
            return total
        except ValueError:
            return None
    try:
        n = float(v)
    except ValueError:
        return None
    if n <= 0:
        return None
    return round(n / 1000, 3) if ms else n


def _m3u(text: str, name: str) -> list[dict]:
    songs, pending = [], None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.upper().startswith("#PLAYLIST:"):
            name = line[10:].strip() or name
        elif line.upper().startswith("#EXTINF:"):
            head, _, title = line[8:].partition(",")
            pending = (_seconds(head.split()[0] if head.split() else ""), title.strip())
        elif line.startswith("#"):
            continue
        else:
            dur, title = pending or (None, "")
            path = "" if re.match(r"^[a-z][a-z0-9+.-]*://", line, re.I) and not line.lower().startswith("file://") else line
            if title:
                songs.append(want(text=title, duration=dur, path=path))
            elif path:
                songs.append(want(path=path, duration=dur))
            pending = None
    return [{"name": name, "songs": songs}] if songs else []


def _pls(text: str, name: str) -> list[dict]:
    entries: dict[int, dict] = defaultdict(dict)
    for line in text.splitlines():
        m = re.match(r"^\s*(File|Title|Length)(\d+)\s*=\s*(.*)$", line, re.I)
        if m:
            entries[int(m.group(2))][m.group(1).lower()] = m.group(3).strip()
    songs = []
    for _, e in sorted(entries.items()):
        path = e.get("file", "")
        if re.match(r"^https?://", path, re.I):
            path = ""
        songs.append(want(text=e.get("title", ""), duration=_seconds(e.get("length")), path=path))
    songs = [s for s in songs if s["text"] or s["path"]]
    return [{"name": name, "songs": songs}] if songs else []


def _xspf(text: str, name: str) -> list[dict]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []

    def child(el, tag):
        for c in el:
            if c.tag.rsplit("}", 1)[-1] == tag:
                return (c.text or "").strip()
        return ""

    name = child(root, "title") or name
    songs = []
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] != "track":
            continue
        loc = child(el, "location")
        songs.append(want(artist=child(el, "creator"), title=child(el, "title"), album=child(el, "album"),
                          duration=_seconds(child(el, "duration"), ms=True),
                          path=loc if loc.lower().startswith("file://") or "://" not in loc else ""))
    return [{"name": name, "songs": songs}] if songs else []


_COLUMNS = {
    "title": ("track name", "track title", "song name", "song title", "title", "song", "name", "track"),
    "artist": ("artist name(s)", "artist names", "artist name", "artist(s)", "artists", "artist", "creator"),
    "album": ("album name", "album title", "album", "release"),
    "duration": ("duration (ms)", "duration_ms", "duration", "length", "time"),
    "playlist": ("playlist name", "playlist"),
}


def _csv(text: str, name: str) -> list[dict]:
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    if len(rows) < 2:
        return []
    header = [h.strip().casefold() for h in rows[0]]
    col = {}
    for key, names in _COLUMNS.items():
        for n in names:
            if n in header:
                col[key] = header.index(n)
                break
    if "title" not in col:
        return []
    ms = "duration" in col and "ms" in header[col["duration"]]
    groups: dict[str, list[dict]] = {}
    for r in rows[1:]:
        def get(key):
            i = col.get(key)
            return r[i].strip() if i is not None and i < len(r) else ""
        title = get("title")
        if not title:
            continue
        group = get("playlist") or name
        groups.setdefault(group, []).append(
            want(artist=get("artist"), title=title, album=get("album"), duration=_seconds(get("duration"), ms=ms)))
    return [{"name": g, "songs": s} for g, s in groups.items()]


def _spotify_json(data) -> list[dict]:
    out = []
    if isinstance(data, dict) and isinstance(data.get("playlists"), list):
        for p in data["playlists"]:
            songs = []
            for item in p.get("items") or []:
                t = item.get("track")
                if isinstance(t, dict) and t.get("trackName"):
                    songs.append(want(artist=t.get("artistName"), title=t.get("trackName"), album=t.get("albumName")))
                    continue
                local = (item.get("localTrack") or {}).get("uri") or ""
                bits = local.split(":")
                if local.startswith("spotify:local:") and len(bits) >= 5:
                    songs.append(want(artist=unquote_plus(bits[2]), album=unquote_plus(bits[3]),
                                      title=unquote_plus(bits[4]), duration=_seconds(bits[5]) if len(bits) > 5 else None))
            if songs:
                out.append({"name": p.get("name") or "Spotify playlist", "songs": songs})
    if isinstance(data, dict) and isinstance(data.get("tracks"), list):
        songs = [want(artist=t.get("artist"), title=t.get("track"), album=t.get("album"))
                 for t in data["tracks"] if isinstance(t, dict) and t.get("track")]
        if songs:
            out.append({"name": "Liked Songs", "songs": songs})
    return out


def _lines(text: str, name: str) -> list[dict]:
    songs = []
    for raw in text.splitlines():
        line = _NUMBERING.sub("", raw).strip()
        if line and not line.startswith("#"):
            songs.append(want(text=line))
    return [{"name": name, "songs": songs}] if songs else []


def parse_file(text: str, filename: str = "") -> list[dict]:
    """The playlists in a file (or pasted text): [{"name", "songs": [want]}]."""
    text = (text or "").lstrip("﻿")
    name = _name_from(filename) if filename else "Imported playlist"
    ext = filename.rsplit(".", 1)[-1].casefold() if "." in filename else ""
    head = text.lstrip()[:200]
    if ext in ("m3u", "m3u8") or head.upper().startswith("#EXTM3U"):
        found = _m3u(text, name)
    elif ext == "pls" or head.casefold().startswith("[playlist]"):
        found = _pls(text, name)
    elif ext == "xspf" or (head.startswith("<") and "xspf" in text[:500]):
        found = _xspf(text, name)
    elif ext == "json" or head.startswith(("{", "[")):
        try:
            found = _spotify_json(json.loads(text))
        except ValueError:
            found = []
    elif ext in ("csv", "tsv"):
        found = _csv(text, name)
    else:
        found = []
        first = text.lstrip().split("\n", 1)[0].casefold()
        if any(sep in first for sep in (",", ";", "\t")) and any(n in first for n in ("title", "track", "song")):
            found = _csv(text, name)
        # A list of file paths from another player, or a list of songs.
        if not found and re.search(r"\.(mp3|flac|m4a|ogg|opus|wav|aac|wma|alac|aiff?)\s*$", head.split("\n", 1)[0], re.I):
            found = _m3u(text, name)
    if not found and ext not in ("json", "xspf"):
        found = _lines(text, name)
    for p in found:
        p["songs"] = p["songs"][:MAX_SONGS]
    return found


# ---------- Spotify and YouTube links ----------

def link(url: str) -> tuple[str, str] | None:
    """("spotify", embed page) or ("youtube", playlist page) for a link to a playlist, else None."""
    url = (url or "").strip()
    if not re.match(r"^https?://", url, re.I) or " " in url:
        return None
    u = urlsplit(url)
    host = (u.hostname or "").casefold()
    if host == "open.spotify.com":
        m = re.search(r"/(playlist|album)/([A-Za-z0-9]+)", u.path)
        return ("spotify", f"https://open.spotify.com/embed/{m.group(1)}/{m.group(2)}") if m else None
    if host in ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"):
        lst = (parse_qs(u.query).get("list") or [""])[0]
        if re.fullmatch(r"[A-Za-z0-9_-]+", lst):
            return ("youtube", f"https://www.youtube.com/playlist?list={lst}")
    return None


def parse_spotify(html: str) -> dict:
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    try:
        entity = json.loads(m.group(1))["props"]["pageProps"]["state"]["data"]["entity"]
        tracks = entity["trackList"]
    except (AttributeError, KeyError, TypeError, ValueError):
        raise ValueError("Spotify didn’t show the songs on that playlist. Check the link, or that the playlist is public.")
    songs = [want(artist=t.get("subtitle", "").replace(" ", " "), title=t.get("title", ""),
                  duration=_seconds(t.get("duration"), ms=True)) for t in tracks if t.get("title")]
    return {"name": entity.get("name") or entity.get("title") or "Spotify playlist", "songs": songs}


def _walk(o, keys, out):
    if isinstance(o, dict):
        for k, v in o.items():
            if k in keys:
                out.append((k, v))
            else:
                _walk(v, keys, out)
    elif isinstance(o, list):
        for v in o:
            _walk(v, keys, out)


def _channel(name: str) -> str:
    """The artist behind a channel name: "Queen - Topic" → "Queen", "TaylorSwiftVEVO" stays a word."""
    return re.sub(r"\s*-\s*Topic$|VEVO$", "", name or "", flags=re.I).strip()


def parse_youtube(html: str) -> dict:
    m = re.search(r"ytInitialData\s*=\s*(\{.*?\});\s*</script>", html, re.S)
    try:
        data = json.loads(m.group(1))
    except (AttributeError, ValueError):
        raise ValueError("YouTube didn’t show that playlist. Check the link, or that the playlist is public or unlisted.")
    found: list = []
    _walk(data, ("playlistVideoRenderer", "lockupViewModel"), found)
    songs = []
    for kind, v in found:
        if kind == "playlistVideoRenderer":
            title = "".join(r.get("text", "") for r in (v.get("title") or {}).get("runs", []))
            channel = "".join(r.get("text", "") for r in (v.get("shortBylineText") or {}).get("runs", []))
            duration = _seconds(v.get("lengthSeconds"))
        else:
            if v.get("contentType", "LOCKUP_CONTENT_TYPE_VIDEO") != "LOCKUP_CONTENT_TYPE_VIDEO":
                continue
            md = (v.get("metadata") or {}).get("lockupMetadataViewModel") or {}
            title = (md.get("title") or {}).get("content", "")
            rows = ((md.get("metadata") or {}).get("contentMetadataViewModel") or {}).get("metadataRows") or []
            parts = [p.get("text", {}).get("content", "") for r in rows[:1] for p in r.get("metadataParts", [])]
            channel = parts[0] if parts else ""
            badges: list = []
            _walk(v.get("contentImage") or {}, ("thumbnailBadgeViewModel",), badges)
            duration = next((_seconds(b.get("text")) for _, b in badges if re.fullmatch(r"\d+(:\d\d)+", b.get("text", ""))), None)
        if title:
            songs.append(want(text=title, artist=_channel(channel), duration=duration))
    if not songs:
        raise ValueError("That YouTube playlist is empty, or YouTube didn’t show it. Check that it’s public or unlisted.")
    name = ((data.get("metadata") or {}).get("playlistMetadataRenderer") or {}).get("title") or "YouTube playlist"
    return {"name": name, "songs": songs}


def fetch(url: str, timeout: float = 20) -> dict:
    """The playlist behind a Spotify or YouTube link (network)."""
    kind, page = link(url) or (None, None)
    if not kind:
        raise ValueError("Shelf can import Spotify and YouTube playlist links.")
    req = urllib.request.Request(page, headers={"User-Agent": UA, "Accept-Language": "en",
                                                "Cookie": "CONSENT=YES+1; SOCS=CAI"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            html = r.read(16 * 1024 * 1024).decode("utf-8", errors="replace")
    except OSError as e:
        raise ValueError(f"Couldn’t open that link ({getattr(e, 'reason', e)}).")
    return parse_spotify(html) if kind == "spotify" else parse_youtube(html)
