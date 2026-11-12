"""The Subsonic API (with the OpenSubsonic additions), so apps made for Subsonic and Navidrome
play from Shelf: Symfonium, Feishin, Substreamer, DSub, Tempo, play:Sub and many more.

Requests are /rest/<method> (or <method>.view), by GET or form POST, answered in XML unless the
app asks for f=json. IDs: a song is its number, an album "al-<n>", an artist "ar-<name in
base64url>", a playlist its number.

Signing in: most apps send a token, the md5 of the password plus a random salt, so the server has
to know the password itself. Shelf never keeps account passwords, only their scrypt hash, so each
person makes an app password in Settings for these apps; it's kept sealed with the server's key.
Apps that send the password itself (p=, plain or enc:hex) can also use the account password.
Wrong passwords count toward the same lockout as the sign-in page.

Stars are Shelf's likes for songs; albums and artists get stars of their own. Scrobbles are
plays (and go on to ListenBrainz and Last.fm). Play counts are everyone's, like the artist page.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from fastapi import Request
from fastapi.responses import FileResponse, Response, StreamingResponse

from . import __version__, covers, credits, lyrics, podcasts, resume, transcode, videos
from . import artists as artist_info
from .subsonic_more import BASE_URL, EXTENSIONS, More
from .auth import verify_password
from .db import T_COLUMNS, get_meta, session, set_meta

API_VERSION = "1.16.1"
XMLNS = "http://subsonic.org/restapi"
IGNORED_ARTICLES = "The El La Los Las Le Les Os As O A"
CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "*"}
NOW_PLAYING_FOR = 15 * 60

TRACKS = f"""
    SELECT {T_COLUMNS}, a.id AS album_id, a.title AS album_title, a.artist AS album_artist_name, a.cover_src
    FROM tracks t JOIN albums a ON a.key = t.album_key
"""
ORDER = "ORDER BY COALESCE(t.disc_no, 1), COALESCE(t.track_no, 9999), t.path"


# ---------- app passwords ----------

def _keystream(key: str, nonce: bytes, n: int) -> bytes:
    out, i = b"", 0
    while len(out) < n:
        out += hmac.new(key.encode(), nonce + i.to_bytes(4, "big"), hashlib.sha256).digest()
        i += 1
    return out[:n]


def seal(key: str, text: str) -> str:
    nonce, data = secrets.token_bytes(12), text.encode()
    return f"v1${nonce.hex()}${bytes(a ^ b for a, b in zip(data, _keystream(key, nonce, len(data)))).hex()}"


def unseal(key: str, sealed: str | None) -> str | None:
    try:
        v, nonce, body = (sealed or "").split("$")
        data = bytes.fromhex(body)
        return bytes(a ^ b for a, b in zip(data, _keystream(key, bytes.fromhex(nonce), len(data)))).decode() if v == "v1" else None
    except ValueError:
        return None


def new_app_password() -> str:
    return secrets.token_urlsafe(15)  # 20 characters


# ---------- IDs ----------

def artist_id(name: str) -> str:
    return "ar-" + base64.urlsafe_b64encode(name.encode()).decode().rstrip("=")


def artist_name(aid: str) -> str | None:
    if not aid.startswith("ar-"):
        return None
    s = aid[3:]
    try:
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)).decode()
    except (ValueError, UnicodeDecodeError):
        return None


def album_num(aid: str) -> int | None:
    return int(aid[3:]) if aid.startswith("al-") and aid[3:].isdigit() else None


def iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z") if ts else None


def index_letter(name: str) -> str:
    words = name.split()
    if len(words) > 1 and words[0].lower() in {a.lower() for a in IGNORED_ARTICLES.split()}:
        name = " ".join(words[1:])
    first = videos.fold(name[:1]).upper()
    return first if first.isalpha() else "#"


def genre_names(tag: str | None) -> list[str]:
    """ "Metal; Hard Rock" -> ["Metal", "Hard Rock"]."""
    out: list[str] = []
    for g in re.split(r"[;/,|]", tag or ""):
        g = g.strip()
        if g and g.lower() not in {o.lower() for o in out}:
            out.append(g)
    return out


def tag_extras(row) -> dict:
    """The less common tags kept for a song or album (MusicBrainz ids, composers, labels...), see tags.extras."""
    try:
        return json.loads(row["extra"] or "{}") if "extra" in row.keys() else {}
    except (TypeError, ValueError):
        return {}


# ---------- answers ----------

class Fail(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def missing(name: str) -> Fail:
    return Fail(10, f"Required parameter is missing: {name}")


def not_found(what: str = "Not found") -> Fail:
    return Fail(70, what)


def _clean(v):
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items() if x is not None}
    if isinstance(v, list):
        return [_clean(x) for x in v]
    return v


def _xml(parent: ET.Element, name: str, value) -> None:
    el = ET.SubElement(parent, name)
    _fill(el, value)


def _fill(el: ET.Element, value: dict) -> None:
    for k, v in value.items():
        if isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    _xml(el, k, item)
                else:
                    ET.SubElement(el, k).text = _attr(item)
        elif isinstance(v, dict):
            _xml(el, k, v)
        elif k == "value":
            el.text = _attr(v)
        else:
            el.set(k, _attr(v))


def _attr(v) -> str:
    return ("true" if v else "false") if isinstance(v, bool) else str(v)


def answer(params, payload: dict | None = None, fail: Fail | None = None) -> Response:
    body = {"status": "failed" if fail else "ok", "version": API_VERSION, "type": "shelf",
            "serverVersion": __version__, "openSubsonic": True}
    if fail:
        body["error"] = {"code": fail.code, "message": fail.message}
    body.update(_clean(payload or {}))
    fmt = (params.get("f") or "xml").lower()
    if fmt in ("json", "jsonp"):
        text = json.dumps({"subsonic-response": body}, ensure_ascii=False)
        cb = params.get("callback")
        if fmt == "jsonp" and cb and re.fullmatch(r"[A-Za-z_$][\w$.]{0,80}", cb):
            return Response(f"{cb}({text});", media_type="application/javascript", headers=CORS)
        return Response(text, media_type="application/json", headers=CORS)
    root = ET.Element("subsonic-response", {"xmlns": XMLNS})
    _fill(root, body)
    return Response(b'<?xml version="1.0" encoding="UTF-8"?>' + ET.tostring(root, encoding="utf-8"),
                    media_type="text/xml; charset=utf-8", headers=CORS)


class Params:
    """Query and form values together; most are single, some (id, songId...) repeat."""

    def __init__(self, items: list[tuple[str, str]]):
        self.items = items
        self.body = None  # a JSON body, for the one call that has one (getTranscodeDecision)

    def get(self, name: str, default=None):
        for k, v in self.items:
            if k == name:
                return v
        return default

    def all(self, name: str) -> list[str]:
        return [v for k, v in self.items if k == name]

    def need(self, name: str) -> str:
        v = self.get(name)
        if v is None or v == "":
            raise missing(name)
        return v

    def int(self, name: str, default: int, lo: int = 0, hi: int = 10**9) -> int:
        try:
            return max(lo, min(hi, int(self.get(name, default))))
        except (TypeError, ValueError):
            return default

    def flag(self, name: str, default: bool) -> bool:
        v = self.get(name)
        return default if v is None else v.lower() in ("true", "1", "yes")


# ---------- the API ----------

class Subsonic(More):
    def __init__(self, cfg, auth, *, scrobbler=None, scanner=None, set_user: Callable | None = None,
                 smart_rows: Callable | None = None, on_played: Callable | None = None,
                 remove_user: Callable | None = None):
        self.cfg, self.auth, self.scrobbler, self.scanner = cfg, auth, scrobbler, scanner
        self.remove_user = remove_user  # an account removed (deleteUser): everything of theirs goes
        self.on_played = on_played or (lambda user_id, track_id: None)  # a listen counted (webhooks)
        self.smart_rows = smart_rows or (lambda conn, row, user_id: None)  # a smart playlist's songs, now
        self.set_user = set_user or (lambda u: None)
        self.now_playing: dict[int, dict] = {}
        self._pw_ok: dict[int, tuple[str, int, float]] = {}  # account passwords checked lately
        self._more_init()

    def db(self):
        return session(self.cfg.db_path)

    # ----- signing in -----

    def app_password(self, user_id: int) -> str | None:
        with self.db() as conn:
            row = conn.execute("SELECT subsonic_secret FROM users WHERE id = ?", (user_id,)).fetchone()
        return unseal(self.cfg.secret_key, row["subsonic_secret"]) if row else None

    def set_app_password(self, user_id: int, password: str | None) -> None:
        with self.db() as conn:
            conn.execute("UPDATE users SET subsonic_secret = ? WHERE id = ?",
                         (seal(self.cfg.secret_key, password) if password else None, user_id))

    def sign_in(self, p: Params, client: str):
        if p.get("apiKey") is not None:
            return self.key_user(p, client)
        name = p.get("u")
        if not name:
            raise missing("u")
        if self.auth.locked_out(client):
            raise Fail(40, "Too many wrong passwords: try again in 15 minutes")
        row = self.auth.find(name)
        user = self.auth.get(row["id"]) if row else None
        secret = self.app_password(row["id"]) if row else None
        token, salt, pw = p.get("t"), p.get("s"), p.get("p")
        ok = False
        if token and salt:
            ok = bool(secret) and hmac.compare_digest(hashlib.md5((secret + salt).encode()).hexdigest(), token.lower())
        elif pw is not None:
            if pw.startswith("enc:"):
                try:
                    pw = bytes.fromhex(pw[4:]).decode()
                except (ValueError, UnicodeDecodeError):
                    pw = ""
            ok = bool(secret) and hmac.compare_digest(secret, pw)
            if not ok and row and user:
                digest = hashlib.sha256(pw.encode()).hexdigest()
                seen = self._pw_ok.get(user.id)
                ok = bool(seen and seen[0] == digest and seen[1] == user.version and seen[2] > time.time())
                if not ok and verify_password(pw, row["pw_hash"]):
                    ok = True
                    self._pw_ok[user.id] = (digest, user.version, time.time() + 600)
        else:
            raise missing("p or t and s")
        if not ok or user is None:
            self.auth.failed(client)
            raise Fail(40, "Wrong username or password")
        return user

    # ----- shaping -----

    def _plays(self, conn) -> dict[int, int]:
        return {r[0]: r[1] for r in conn.execute("SELECT track_id, COUNT(*) FROM plays GROUP BY track_id")}

    def _liked(self, conn, uid: int) -> dict[int, float]:
        return {r[0]: r[1] for r in conn.execute("SELECT track_id, liked_at FROM likes WHERE user_id = ?", (uid,))}

    def _stars(self, conn, uid: int, kind: str) -> dict[str, float]:
        return {r[0]: r[1] for r in conn.execute("SELECT ref, at FROM stars WHERE user_id = ? AND kind = ?", (uid, kind))}

    def _ctx(self, conn, uid: int) -> dict:
        return {"plays": self._plays(conn), "liked": self._liked(conn, uid),
                "played": {r[0]: r[1] for r in conn.execute(
                    "SELECT track_id, MAX(played_at) FROM plays WHERE user_id = ? GROUP BY track_id", (uid,))},
                "marks": {r[0]: r[1] for r in conn.execute(
                    "SELECT track_id, position FROM resume_points WHERE user_id = ?", (uid,))}}

    def song(self, r, ctx: dict) -> dict:
        path = Path(r["path"])
        ext = path.suffix.lstrip(".").lower()
        names = credits.names(r["artist"]) or [r["artist"]]
        album_artist = r["album_artist_name"] or r["artist"]
        album_names = credits.names(album_artist) or [album_artist]
        extra = tag_extras(r)
        gain = {"trackGain": round(-18 - r["lufs"], 2), "trackPeak": round(10 ** (r["peak"] / 20), 6) if r["peak"] is not None else None} \
            if r["lufs"] is not None else {}
        liked = ctx["liked"].get(r["id"])
        mark = ctx.get("marks", {}).get(r["id"])
        return {
            "id": str(r["id"]), "parent": f"al-{r['album_id']}", "isDir": False, "title": r["title"],
            "album": r["album_title"], "artist": r["artist"], "track": r["track_no"], "discNumber": r["disc_no"],
            "year": r["year"], "genre": r["genre"] or None,
            "coverArt": f"al-{r['album_id']}" if r["cover_src"] else None,
            "size": r["size"], "contentType": r["mime"] or mimetypes.guess_type(path.name)[0] or "audio/mpeg",
            "suffix": ext, "duration": int(round(r["duration"] or 0)),
            "bitRate": (r["bitrate"] or 0) // 1000 or None, "samplingRate": r["sample_rate"], "bitDepth": r["bits"],
            "channelCount": extra.get("channels"),
            "path": f"{album_artist}/{r['album_title']}/{path.name}",
            "albumId": f"al-{r['album_id']}", "artistId": artist_id(names[0]), "type": "music", "mediaType": "song",
            "created": iso(r["added_at"]), "playCount": ctx["plays"].get(r["id"], 0),
            "played": iso(ctx.get("played", {}).get(r["id"])),
            "starred": iso(liked), "userRating": 5 if liked else None,
            "bookmarkPosition": int(mark * 1000) if mark else None,
            "bpm": int(round(r["bpm"])) if "bpm" in r.keys() and r["bpm"] else 0,
            "comment": extra.get("comment", ""), "sortName": extra.get("sort", ""),
            "musicBrainzId": extra.get("mbid", ""), "isrc": extra.get("isrc", []),
            "genres": [{"name": g} for g in genre_names(r["genre"])],
            "artists": [{"id": artist_id(n), "name": n} for n in names], "displayArtist": r["artist"],
            "albumArtists": [{"id": artist_id(n), "name": n} for n in album_names], "displayAlbumArtist": album_artist,
            "contributors": [{"role": "composer", "artist": {"id": artist_id(n), "name": n}} for n in extra.get("composers", [])],
            "displayComposer": ", ".join(extra.get("composers", [])),
            "moods": extra.get("moods", []), "explicitStatus": extra.get("explicit", ""),
            "replayGain": gain,
        }

    def album(self, r, ctx: dict) -> dict:
        names = credits.names(r["artist"]) or [r["artist"]]
        first = names[0]
        extra = tag_extras(r)
        return {
            "id": f"al-{r['id']}", "parent": artist_id(first), "isDir": True,
            "name": r["title"], "title": r["title"], "album": r["title"], "artist": r["artist"],
            "artistId": artist_id(first), "coverArt": f"al-{r['id']}" if r["cover_src"] else None,
            "songCount": r["track_count"], "duration": int(round(r["duration"] or 0)),
            "created": iso(r["added_at"]), "year": r["year"], "genre": r["genre"] or None,
            "playCount": ctx.get("album_plays", {}).get(r["key"], 0),
            "played": iso(ctx.get("album_played", {}).get(r["key"])),
            "starred": iso(ctx.get("album_stars", {}).get(r["key"])),
            "artists": [{"id": artist_id(n), "name": n} for n in names], "displayArtist": r["artist"],
            "genres": [{"name": g} for g in genre_names(r["genre"])],
            "musicBrainzId": extra.get("album_mbid", ""), "sortName": extra.get("album_sort", ""),
            "isCompilation": bool(extra.get("compilation")) or videos.fold(r["artist"]) == "various artists",
            "releaseTypes": extra.get("release_types", []),
            "recordLabels": [{"name": n} for n in extra.get("labels", [])],
            "releaseDate": {"year": r["year"]} if r["year"] else {},
            "originalReleaseDate": {"year": extra["original_year"]} if extra.get("original_year") else {},
            "moods": [], "discTitles": [], "explicitStatus": extra.get("explicit", ""), "version": "",
        }

    def _album_ctx(self, conn, uid: int) -> dict:
        return {"album_plays": {r[0]: r[1] for r in conn.execute("SELECT album_key, COUNT(*) FROM plays GROUP BY album_key")},
                "album_played": {r[0]: r[1] for r in conn.execute(
                    "SELECT album_key, MAX(played_at) FROM plays WHERE user_id = ? GROUP BY album_key", (uid,))},
                "album_stars": self._stars(conn, uid, "album")}

    # ----- music folders (musicFolderId) -----

    def folders(self) -> list[Path]:
        return [Path(d).resolve() for d in self.cfg.music_dirs]  # as the scanner stores paths

    def _folder_like(self, p) -> str | None:
        """The LIKE pattern for the songs in the music folder the app asked for, or None for all."""
        raw = p.get("musicFolderId")
        if raw in (None, ""):
            return None
        folders = self.folders()
        if not raw.isdigit() or not 1 <= int(raw) <= len(folders):
            raise not_found("No such music folder")
        base = str(folders[int(raw) - 1]).rstrip("/\\") + os.sep  # "/music/", so /music2 isn't in it
        return base.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"

    @staticmethod
    def _in_folder(alias: str = "a") -> str:
        return f"EXISTS (SELECT 1 FROM tracks x WHERE x.album_key = {alias}.key AND x.path LIKE ? ESCAPE '\\')"

    def _artists(self, conn, folder: str | None = None) -> dict[str, dict]:
        """Every artist with their albums (a shared album counts for each of its artists)."""
        by: dict[str, dict] = {}
        where, args = (f"WHERE {self._in_folder('albums')}", (folder,)) if folder else ("", ())
        for r in conn.execute(f"SELECT * FROM albums {where} ORDER BY COALESCE(year, 9999), title COLLATE NOCASE", args):
            for name in credits.names(r["artist"]) or [r["artist"]]:
                by.setdefault(videos.fold(name), {"name": name, "albums": []})["albums"].append(r)
        return by

    def artist(self, a: dict, stars: dict) -> dict:
        cover = max(a["albums"], key=lambda r: (bool(r["cover_src"]), r["track_count"]), default=None)
        return {"id": artist_id(a["name"]), "name": a["name"], "albumCount": len(a["albums"]),
                "coverArt": artist_id(a["name"]) if cover is not None and cover["cover_src"] else None,
                "starred": iso(stars.get(videos.fold(a["name"])))}

    def _find_artist(self, conn, aid: str) -> dict:
        name = artist_name(aid)
        a = self._artists(conn).get(videos.fold(name)) if name else None
        if not a:
            raise not_found("Artist not found")
        return a

    def _album_row(self, conn, aid: str):
        n = album_num(aid)
        row = conn.execute("SELECT * FROM albums WHERE id = ?", (n,)).fetchone() if n is not None else None
        if not row:
            raise not_found("Album not found")
        return row

    def _track_row(self, conn, tid: str):
        row = conn.execute(f"{TRACKS} WHERE t.id = ?", (int(tid),)).fetchone() if tid.isdigit() else None
        if not row:
            raise not_found("Song not found")
        return row

    # ----- methods -----

    def call(self, method: str, p: Params, user, request: Request):
        fn = getattr(self, "m_" + method, None)
        if fn is None:
            raise Fail(0, f"Unknown method: {method}")
        return fn(p, user)

    def m_ping(self, p, user):
        return {}

    def m_getLicense(self, p, user):
        return {"license": {"valid": True, "email": "", "licenseExpires": "2100-01-01T00:00:00.000Z"}}

    def m_getOpenSubsonicExtensions(self, p, user):
        return {"openSubsonicExtensions": [{"name": n, "versions": [v]} for n, v in EXTENSIONS]}

    def m_getMusicFolders(self, p, user):
        return {"musicFolders": {"musicFolder": [{"id": n, "name": Path(d).name or str(d)}
                                                 for n, d in enumerate(self.folders(), 1)] or [{"id": 1, "name": "Music"}]}}

    def m_getUser(self, p, user):
        name = p.get("username") or user.username
        if name.casefold() != user.username.casefold() and not user.admin:
            raise Fail(50, "Only an admin can see other people")
        row = self.auth.find(name)
        if not row:
            raise not_found("No such person")
        return {"user": self._user(row)}

    def m_getUsers(self, p, user):
        if not user.admin:
            raise Fail(50, "Only an admin can see other people")
        with self.db() as conn:
            rows = conn.execute("SELECT * FROM users ORDER BY username").fetchall()
        return {"users": {"user": [self._user(r) for r in rows]}}

    def _user(self, row) -> dict:
        admin = bool(row["is_admin"])
        return {"username": row["username"], "email": "", "scrobblingEnabled": True, "adminRole": admin,
                "settingsRole": True, "downloadRole": True, "uploadRole": admin, "playlistRole": True,
                "coverArtRole": admin, "commentRole": False, "podcastRole": True, "streamRole": True,
                "jukeboxRole": False, "shareRole": self._sharing(), "videoConversionRole": False,
                "folder": list(range(1, len(self.folders()) + 1)) or [1]}

    def _sharing(self) -> bool:
        from . import shares
        with self.db() as conn:
            return shares.enabled(conn)

    def m_getScanStatus(self, p, user):
        with self.db() as conn:
            count = conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
        running = bool(self.scanner and self.scanner.state.get("running"))
        return {"scanStatus": {"scanning": running, "count": count}}

    def m_startScan(self, p, user):
        if not user.admin:
            raise Fail(50, "Only an admin can rescan the library")
        if self.scanner:
            self.scanner.trigger()
        return self.m_getScanStatus(p, user)

    # browsing

    def m_getArtists(self, p, user):
        with self.db() as conn:
            artists, stars = self._artists(conn, self._folder_like(p)), self._stars(conn, user.id, "artist")
        return {"artists": {"ignoredArticles": IGNORED_ARTICLES, "index": self._index(artists, stars)}}

    def _index(self, artists: dict, stars: dict) -> list[dict]:
        groups: dict[str, list] = {}
        for a in sorted(artists.values(), key=lambda a: videos.fold(a["name"])):
            groups.setdefault(index_letter(a["name"]), []).append(self.artist(a, stars))
        return [{"name": k, "artist": groups[k]} for k in sorted(groups, key=lambda k: (k == "#", k))]

    def m_getIndexes(self, p, user):
        with self.db() as conn:
            artists, stars = self._artists(conn, self._folder_like(p)), self._stars(conn, user.id, "artist")
            changed = conn.execute("SELECT MAX(added_at) FROM albums").fetchone()[0] or 0
        return {"indexes": {"lastModified": int(changed * 1000), "ignoredArticles": IGNORED_ARTICLES,
                            "index": self._index(artists, stars)}}

    def m_getArtist(self, p, user):
        with self.db() as conn:
            a = self._find_artist(conn, p.need("id"))
            ctx = self._album_ctx(conn, user.id)
            stars = self._stars(conn, user.id, "artist")
        return {"artist": {**self.artist(a, stars), "album": [self.album(r, ctx) for r in a["albums"]]}}

    def m_getAlbum(self, p, user):
        with self.db() as conn:
            row = self._album_row(conn, p.need("id"))
            ctx = {**self._ctx(conn, user.id), **self._album_ctx(conn, user.id)}
            tracks = conn.execute(f"{TRACKS} WHERE a.id = ? {ORDER}", (row["id"],)).fetchall()
        return {"album": {**self.album(row, ctx), "song": [self.song(t, ctx) for t in tracks]}}

    def m_getSong(self, p, user):
        with self.db() as conn:
            row = self._track_row(conn, p.need("id"))
            ctx = self._ctx(conn, user.id)
        return {"song": self.song(row, ctx)}

    def m_getMusicDirectory(self, p, user):
        did = p.need("id")
        with self.db() as conn:
            if did.startswith("ar-"):
                a = self._find_artist(conn, did)
                ctx = self._album_ctx(conn, user.id)
                return {"directory": {"id": did, "name": a["name"], "child": [self.album(r, ctx) for r in a["albums"]]}}
            row = self._album_row(conn, did)
            ctx = self._ctx(conn, user.id)
            tracks = conn.execute(f"{TRACKS} WHERE a.id = ? {ORDER}", (row["id"],)).fetchall()
        first = (credits.names(row["artist"]) or [row["artist"]])[0]
        return {"directory": {"id": did, "parent": artist_id(first), "name": row["title"],
                              "child": [self.song(t, ctx) for t in tracks]}}

    def m_getGenres(self, p, user):
        with self.db() as conn:
            rows = conn.execute(
                "SELECT genre, COUNT(*) AS songs, COUNT(DISTINCT album_key) AS albums FROM tracks"
                " WHERE genre IS NOT NULL AND genre != '' GROUP BY genre COLLATE NOCASE ORDER BY genre COLLATE NOCASE").fetchall()
        return {"genres": {"genre": [{"value": r["genre"], "songCount": r["songs"], "albumCount": r["albums"]} for r in rows]}}

    # lists

    def _album_list(self, p, user) -> list[dict]:
        kind = p.need("type")
        size, offset = p.int("size", 10, 1, 500), p.int("offset", 0)
        where, args, order = "", [], "a.title COLLATE NOCASE"
        join = ""
        if kind == "random":
            order = "RANDOM()"
        elif kind == "newest":
            order = "a.added_at DESC"
        elif kind == "alphabeticalByName":
            order = "a.title COLLATE NOCASE"
        elif kind == "alphabeticalByArtist":
            order = "a.artist COLLATE NOCASE, COALESCE(a.year, 9999), a.title COLLATE NOCASE"
        elif kind in ("recent", "frequent"):
            join = "JOIN (SELECT album_key, MAX(played_at) AS last, COUNT(*) AS n FROM plays WHERE user_id = ? GROUP BY album_key) pl ON pl.album_key = a.key"
            args.append(user.id)
            order = "pl.last DESC" if kind == "recent" else "pl.n DESC, pl.last DESC"
        elif kind == "highest":  # no ratings in Shelf: the most played, by everyone
            join = "JOIN (SELECT album_key, COUNT(*) AS n FROM plays GROUP BY album_key) pl ON pl.album_key = a.key"
            order = "pl.n DESC"
        elif kind == "starred":
            join = "JOIN stars s ON s.ref = a.key AND s.kind = 'album' AND s.user_id = ?"
            args.append(user.id)
            order = "s.at DESC"
        elif kind == "byYear":
            lo, hi = p.int("fromYear", 0), p.int("toYear", 9999)
            where = "WHERE a.year BETWEEN ? AND ?"
            args += [min(lo, hi), max(lo, hi)]
            order = "a.year DESC" if lo > hi else "a.year"
        elif kind == "byGenre":
            where = "WHERE a.genre = ? COLLATE NOCASE"
            args.append(p.need("genre"))
        else:
            raise Fail(0, f"Unknown list type: {kind}")
        folder = self._folder_like(p)
        if folder:
            where = (where + " AND " if where else "WHERE ") + self._in_folder("a")
            args.append(folder)
        with self.db() as conn:
            rows = conn.execute(f"SELECT a.* FROM albums a {join} {where} ORDER BY {order} LIMIT ? OFFSET ?",
                                (*args, size, offset)).fetchall()
            ctx = self._album_ctx(conn, user.id)
        return [self.album(r, ctx) for r in rows]

    def m_getAlbumList2(self, p, user):
        return {"albumList2": {"album": self._album_list(p, user)}}

    def m_getAlbumList(self, p, user):
        return {"albumList": {"album": self._album_list(p, user)}}

    def _songs(self, user, where: str, args: tuple, order: str, limit: int, offset: int = 0) -> list[dict]:
        with self.db() as conn:
            rows = conn.execute(f"{TRACKS} {where} ORDER BY {order} LIMIT ? OFFSET ?", (*args, limit, offset)).fetchall()
            ctx = self._ctx(conn, user.id)
        return [self.song(r, ctx) for r in rows]

    def m_getRandomSongs(self, p, user):
        clauses, args = [], []
        if p.get("genre"):
            clauses.append("t.genre = ? COLLATE NOCASE")
            args.append(p.get("genre"))
        if p.get("fromYear"):
            clauses.append("t.year >= ?")
            args.append(p.int("fromYear", 0))
        if p.get("toYear"):
            clauses.append("t.year <= ?")
            args.append(p.int("toYear", 9999))
        if self._folder_like(p):
            clauses.append("t.path LIKE ? ESCAPE '\\'")
            args.append(self._folder_like(p))
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        return {"randomSongs": {"song": self._songs(user, where, tuple(args), "RANDOM()", p.int("size", 10, 1, 500))}}

    def m_getSongsByGenre(self, p, user):
        folder = self._folder_like(p)
        where = "WHERE t.genre = ? COLLATE NOCASE" + (" AND t.path LIKE ? ESCAPE '\\'" if folder else "")
        return {"songsByGenre": {"song": self._songs(user, where, (p.need("genre"), *([folder] if folder else [])),
                                                     "t.artist COLLATE NOCASE, t.album, t.track_no",
                                                     p.int("count", 10, 1, 500), p.int("offset", 0))}}

    def m_getTopSongs(self, p, user):
        name = artist_name(p.get("id")) if p.get("id") else None
        name = name or p.need("artist")
        count = p.int("count", 50, 1, 500)
        with self.db() as conn:
            rows = conn.execute(f"""{TRACKS} LEFT JOIN (SELECT track_id, COUNT(*) AS n FROM plays GROUP BY track_id) pl
                ON pl.track_id = t.id ORDER BY COALESCE(pl.n, 0) DESC, t.title""").fetchall()
            rows = [r for r in rows if credits.credited(r["artist"], name) or credits.credited(r["album_artist_name"], name)][:count]
            ctx = self._ctx(conn, user.id)
        return {"topSongs": {"song": [self.song(r, ctx) for r in rows]}}

    def _similar(self, p, user, count_default=50) -> list[dict]:
        sid, count = p.need("id"), p.int("count", count_default, 1, 500)
        with self.db() as conn:
            if sid.startswith("ar-"):
                a = self._find_artist(conn, sid)
                seed = conn.execute(f"{TRACKS} WHERE a.id = ? LIMIT 1", (a["albums"][0]["id"],)).fetchone()
            elif sid.startswith("al-"):
                seed = conn.execute(f"{TRACKS} WHERE a.id = ? LIMIT 1", (self._album_row(conn, sid)["id"],)).fetchone()
            else:
                seed = self._track_row(conn, sid)
            alike = self.sonic_similar(conn, seed["id"], count, seed["album_key"]) if not sid.startswith("ar-") else None
            if alike:  # the songs that sound most like it
                found = {r["id"]: r for r in conn.execute(f"{TRACKS} WHERE t.id IN ({','.join('?' * len(alike))})", alike)}
                rows = [found[i] for i in alike if i in found]
            else:  # not measured yet: the same artist or genre
                rows = conn.execute(
                    f"""{TRACKS} WHERE t.id != ? AND (a.artist = ? COLLATE NOCASE OR (t.genre IS NOT NULL AND t.genre != '' AND t.genre = ? COLLATE NOCASE))
                    ORDER BY (t.album_key = ?), RANDOM() LIMIT ?""",
                    (seed["id"], seed["album_artist_name"], seed["genre"], seed["album_key"], count)).fetchall()
            ctx = self._ctx(conn, user.id)
        return [self.song(r, ctx) for r in rows]

    def m_getSimilarSongs2(self, p, user):
        return {"similarSongs2": {"song": self._similar(p, user)}}

    def m_getSimilarSongs(self, p, user):
        return {"similarSongs": {"song": self._similar(p, user)}}

    def _info(self, p, user) -> dict:
        with self.db() as conn:
            a = self._find_artist(conn, p.need("id"))
            names = self.similar_artists(conn, a["name"], p.int("count", 20, 0, 100))
            everyone, stars = self._artists(conn), self._stars(conn, user.id, "artist")
            mbid = ""
            for r in conn.execute("SELECT artist, extra FROM tracks WHERE album_key IN (%s) AND extra LIKE '%%artist_mbid%%' LIMIT 50"
                                  % ",".join("?" * len(a["albums"])), [r["key"] for r in a["albums"]]):
                got = tag_extras(r)  # the id is the song's first artist's
                if got.get("artist_mbid") and videos.fold((credits.names(r["artist"]) or [""])[0]) == videos.fold(a["name"]):
                    mbid = got["artist_mbid"]
                    break
        about = None
        if getattr(self.cfg, "artist_info", False):
            _, about = artist_info.cached(self.cfg.db_path, videos.fold(a["name"]), "about")
        similar = [self.artist(everyone[videos.fold(n)], stars) for n in names if videos.fold(n) in everyone]
        return {"biography": (about or {}).get("extract") or "", "musicBrainzId": mbid, "similarArtist": similar}

    def m_getArtistInfo2(self, p, user):
        return {"artistInfo2": self._info(p, user)}

    def m_getArtistInfo(self, p, user):
        return {"artistInfo": self._info(p, user)}

    def m_getAlbumInfo(self, p, user):
        sid = p.need("id")
        with self.db() as conn:
            if sid.isdigit():  # a song's album
                row = self._album_row(conn, f"al-{self._track_row(conn, sid)['album_id']}")
            else:
                row = self._album_row(conn, sid)
        return {"albumInfo": {"notes": "", "musicBrainzId": tag_extras(row).get("album_mbid", "")}}

    def m_getAlbumInfo2(self, p, user):
        return self.m_getAlbumInfo(p, user)

    # searching

    def _search(self, p, user) -> tuple[list, list, list]:
        q = (p.get("query") or "").strip().strip('"').strip()
        terms = [t for t in q.split() if t][:6]
        folded = [videos.fold(t) for t in terms]

        def like(cols):
            clauses, args = [], []
            for t in terms:
                pat = "%" + t.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                clauses.append("(" + " OR ".join(f"{c} LIKE ? ESCAPE '\\'" for c in cols) + ")")
                args += [pat] * len(cols)
            return ("WHERE " + " AND ".join(clauses)) if clauses else "", tuple(args)

        folder = self._folder_like(p)

        def within(w: str, args: tuple, cond: str) -> tuple[str, tuple]:
            if not folder:
                return w, args
            return (f"{w} AND {cond}" if w else f"WHERE {cond}"), (*args, folder)

        with self.db() as conn:
            stars = self._stars(conn, user.id, "artist")
            artists = sorted((a for a in self._artists(conn, folder).values() if all(f in videos.fold(a["name"]) for f in folded)),
                             key=lambda a: videos.fold(a["name"]))
            ao, ac = p.int("artistOffset", 0), p.int("artistCount", 20, 0, 5000)
            artists = [self.artist(a, stars) for a in artists[ao:ao + ac]]
            w, args = within(*like(["a.title", "a.artist"]), self._in_folder("a"))
            albums = conn.execute(f"SELECT a.* FROM albums a {w} ORDER BY a.artist COLLATE NOCASE, a.year, a.id LIMIT ? OFFSET ?",
                                  (*args, p.int("albumCount", 20, 0, 5000), p.int("albumOffset", 0))).fetchall()
            actx = self._album_ctx(conn, user.id)
            w, args = within(*like(["t.title", "t.artist", "a.title"]), "t.path LIKE ? ESCAPE '\\'")
            order = "t.title COLLATE NOCASE, t.id" if terms else "t.id"  # all of it: in a steady order, for syncing
            songs = conn.execute(f"{TRACKS} {w} ORDER BY {order} LIMIT ? OFFSET ?",
                                 (*args, p.int("songCount", 20, 0, 50000), p.int("songOffset", 0))).fetchall()
            ctx = self._ctx(conn, user.id)
        return artists, [self.album(r, actx) for r in albums], [self.song(r, ctx) for r in songs]

    def m_search(self, p, user):
        """The first search: songs matching any of artist, album, title or anything."""
        clauses, args = [], []
        for name, cols in (("artist", ["t.artist", "a.artist"]), ("album", ["a.title"]), ("title", ["t.title"]),
                           ("any", ["t.title", "t.artist", "a.title"])):
            v = (p.get(name) or "").strip()
            if v:
                pat = "%" + v.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                clauses.append("(" + " OR ".join(f"{c} LIKE ? ESCAPE '\\'" for c in cols) + ")")
                args += [pat] * len(cols)
        if p.get("newerThan"):
            clauses.append("t.added_at > ?")
            args.append(p.int("newerThan", 0, 0, 10**14) / 1000)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        count, offset = p.int("count", 20, 1, 500), p.int("offset", 0)
        with self.db() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM tracks t JOIN albums a ON a.key = t.album_key {where}", args).fetchone()[0]
        songs = self._songs(user, where, tuple(args), "t.title COLLATE NOCASE, t.id", count, offset)
        return {"searchResult": {"offset": offset, "totalHits": total, "match": songs}}

    def m_search3(self, p, user):
        artists, albums, songs = self._search(p, user)
        return {"searchResult3": {"artist": artists, "album": albums, "song": songs}}

    def m_search2(self, p, user):
        artists, albums, songs = self._search(p, user)
        return {"searchResult2": {"artist": artists, "album": albums, "song": songs}}

    # stars

    def _star(self, p, user, on: bool):
        now = time.time()
        with self.db() as conn:
            for sid in p.all("id"):
                if sid.startswith("al-"):  # some apps star albums by id=
                    self._set_star(conn, user.id, "album", self._album_row(conn, sid)["key"], on, now)
                elif sid.startswith("ar-"):
                    self._set_star(conn, user.id, "artist", videos.fold(self._find_artist(conn, sid)["name"]), on, now)
                else:
                    tid = self._track_row(conn, sid)["id"]
                    if on:
                        conn.execute("INSERT OR IGNORE INTO likes(user_id, track_id, liked_at) VALUES(?, ?, ?)", (user.id, tid, now))
                    else:
                        conn.execute("DELETE FROM likes WHERE user_id = ? AND track_id = ?", (user.id, tid))
            for aid in p.all("albumId"):
                self._set_star(conn, user.id, "album", self._album_row(conn, aid)["key"], on, now)
            for aid in p.all("artistId"):
                self._set_star(conn, user.id, "artist", videos.fold(self._find_artist(conn, aid)["name"]), on, now)
        return {}

    @staticmethod
    def _set_star(conn, uid: int, kind: str, ref: str, on: bool, now: float) -> None:
        if on:
            conn.execute("INSERT OR IGNORE INTO stars(user_id, kind, ref, at) VALUES(?, ?, ?, ?)", (uid, kind, ref, now))
        else:
            conn.execute("DELETE FROM stars WHERE user_id = ? AND kind = ? AND ref = ?", (uid, kind, ref))

    def m_star(self, p, user):
        return self._star(p, user, True)

    def m_unstar(self, p, user):
        return self._star(p, user, False)

    def m_setRating(self, p, user):  # Shelf has no ratings; five stars counts as a like
        rating = p.int("rating", 0, 0, 5)
        sid = p.need("id")
        if rating == 5 or (rating == 0 and not sid.startswith(("al-", "ar-"))):
            self._star(Params([("id", sid)]), user, rating == 5)
        return {}

    def _starred(self, user) -> dict:
        with self.db() as conn:
            rows = conn.execute(f"{TRACKS} JOIN likes l ON l.track_id = t.id AND l.user_id = ? ORDER BY l.liked_at DESC",
                                (user.id,)).fetchall()
            ctx = {**self._ctx(conn, user.id), **self._album_ctx(conn, user.id)}
            albums = conn.execute("SELECT a.* FROM albums a JOIN stars s ON s.ref = a.key AND s.kind = 'album'"
                                  " AND s.user_id = ? ORDER BY s.at DESC", (user.id,)).fetchall()
            stars = self._stars(conn, user.id, "artist")
            everyone = self._artists(conn)
        artists = [self.artist(everyone[k], stars) for k in stars if k in everyone]
        return {"artist": artists, "album": [self.album(r, ctx) for r in albums], "song": [self.song(r, ctx) for r in rows]}

    def m_getStarred2(self, p, user):
        return {"starred2": self._starred(user)}

    def m_getStarred(self, p, user):
        return {"starred": self._starred(user)}

    # playlists

    def _playlist(self, conn, row, user, tracks: list | None = None) -> dict:
        tracks = tracks if tracks is not None else self._playlist_tracks(conn, row, user)
        first = next((t for t in tracks if t["cover_src"]), None)
        owner = conn.execute("SELECT username FROM users WHERE id = ?", (row["user_id"],)).fetchone()
        return {"id": str(row["id"]), "name": row["name"], "comment": row["description"] or None,
                "owner": owner["username"] if owner else None, "public": row["shared"] >= 1,
                "songCount": len(tracks), "duration": int(round(sum(t["duration"] or 0 for t in tracks))),
                "created": iso(row["created_at"]), "changed": iso(row["updated_at"]),
                "coverArt": f"al-{first['album_id']}" if first else None}

    def _playlist_tracks(self, conn, row, user) -> list:
        picked = self.smart_rows(conn, row, user.id)
        if picked is not None:
            return picked
        return conn.execute(f"SELECT q.* FROM playlist_tracks e JOIN ({TRACKS}) q ON q.id = e.track_id"
                            " WHERE e.playlist_id = ? ORDER BY e.position", (row["id"],)).fetchall()

    def _playlist_row(self, conn, pid: str, user, need: str = "read"):
        row = conn.execute("SELECT * FROM playlists WHERE id = ?", (int(pid),)).fetchone() if pid.isdigit() else None
        mine = row is not None and row["user_id"] == user.id
        if row is None or not (mine or (need == "read" and row["shared"] >= 1) or (need == "tracks" and row["shared"] == 2)):
            if row is not None and row["shared"] >= 1:
                raise Fail(50, "Only the person who made this playlist can change it")
            raise not_found("Playlist not found")
        return row

    def m_getPlaylists(self, p, user):
        with self.db() as conn:
            rows = conn.execute("SELECT * FROM playlists WHERE user_id = ? OR shared >= 1 ORDER BY updated_at DESC",
                                (user.id,)).fetchall()
            return {"playlists": {"playlist": [self._playlist(conn, r, user) for r in rows]}}

    def m_getPlaylist(self, p, user):
        with self.db() as conn:
            row = self._playlist_row(conn, p.need("id"), user)
            tracks = self._playlist_tracks(conn, row, user)
            ctx = self._ctx(conn, user.id)
            return {"playlist": {**self._playlist(conn, row, user, tracks), "entry": [self.song(t, ctx) for t in tracks]}}

    @staticmethod
    def _add_songs(conn, pid: int, ids: list[str], uid: int) -> None:
        nums = [int(i) for i in ids if i.isdigit()]
        known = {r[0] for r in conn.execute(f"SELECT id FROM tracks WHERE id IN ({','.join('?' * len(nums))})", nums)} if nums else set()
        start = conn.execute("SELECT COALESCE(MAX(position), 0) FROM playlist_tracks WHERE playlist_id = ?", (pid,)).fetchone()[0]
        now = time.time()
        conn.executemany("INSERT INTO playlist_tracks(playlist_id, track_id, position, added_at, added_by) VALUES(?, ?, ?, ?, ?)",
                         [(pid, t, start + i + 1, now, uid) for i, t in enumerate(n for n in nums if n in known)])

    def m_createPlaylist(self, p, user):
        now = time.time()
        with self.db() as conn:
            if p.get("playlistId"):  # replace an existing one's songs
                row = self._playlist_row(conn, p.get("playlistId"), user, "owner")
                if row["rules"]:
                    raise Fail(50, "That’s a smart playlist: its rules pick the songs")
                pid = row["id"]
                conn.execute("DELETE FROM playlist_tracks WHERE playlist_id = ?", (pid,))
                if p.get("name"):
                    conn.execute("UPDATE playlists SET name = ? WHERE id = ?", (p.get("name")[:200], pid))
            else:
                name = p.need("name")[:200]
                pid = conn.execute("INSERT INTO playlists(name, description, created_at, updated_at, user_id) VALUES(?, '', ?, ?, ?)",
                                   (name, now, now, user.id)).lastrowid
            self._add_songs(conn, pid, p.all("songId"), user.id)
            conn.execute("UPDATE playlists SET updated_at = ? WHERE id = ?", (now, pid))
        return self.m_getPlaylist(Params([("id", str(pid))]), user)

    def m_updatePlaylist(self, p, user):
        pid = p.need("playlistId")
        renaming = any(p.get(k) is not None for k in ("name", "comment", "public"))
        with self.db() as conn:
            row = self._playlist_row(conn, pid, user, "owner" if renaming else "tracks")
            if row["rules"] and (p.all("songIdToAdd") or p.all("songIndexToRemove")):
                raise Fail(50, "That’s a smart playlist: its rules pick the songs")
            if p.get("name"):
                conn.execute("UPDATE playlists SET name = ? WHERE id = ?", (p.get("name")[:200], row["id"]))
            if p.get("comment") is not None:
                conn.execute("UPDATE playlists SET description = ? WHERE id = ?", (p.get("comment")[:2000], row["id"]))
            if p.get("public") is not None:
                public = p.flag("public", False)
                shared = max(row["shared"], 1) if public else 0
                conn.execute("UPDATE playlists SET shared = ? WHERE id = ?", (shared, row["id"]))
            drop = {int(i) for i in p.all("songIndexToRemove") if i.isdigit()}
            if drop:
                entries = [r[0] for r in conn.execute("SELECT id FROM playlist_tracks WHERE playlist_id = ? ORDER BY position", (row["id"],))]
                gone = [entries[i] for i in drop if i < len(entries)]
                conn.executemany("DELETE FROM playlist_tracks WHERE id = ?", [(e,) for e in gone])
            self._add_songs(conn, row["id"], p.all("songIdToAdd"), user.id)
            conn.execute("UPDATE playlists SET updated_at = ? WHERE id = ?", (time.time(), row["id"]))
        return {}

    def m_deletePlaylist(self, p, user):
        with self.db() as conn:
            row = self._playlist_row(conn, p.need("id"), user, "owner")
            conn.execute("DELETE FROM playlists WHERE id = ?", (row["id"],))
        return {}

    # playing

    def m_scrobble(self, p, user):
        ids = p.all("id")
        if not ids:
            raise missing("id")
        submission = p.flag("submission", True)
        times = p.all("time")
        now = time.time()
        with self.db() as conn:
            for i, sid in enumerate(ids):
                if self.episode_num(sid) is not None:  # a podcast episode: never a play
                    e = self._episode_row(conn, sid)
                    if submission:
                        podcasts.mark(conn, user.id, e["id"], True)
                    else:
                        self.now_playing[user.id] = {"track": podcasts.EP_BASE + e["id"], "at": now, "player": p.get("c") or "app"}
                    continue
                row = self._track_row(conn, sid)
                if not submission:
                    self.now_playing[user.id] = {"track": row["id"], "at": now, "player": p.get("c") or "app"}
                    continue
                try:
                    when = int(times[i]) / 1000 if i < len(times) else now
                except ValueError:
                    when = now
                when = when if now - 60 * 86400 <= when <= now + 60 else now
                conn.execute("INSERT INTO plays(track_id, album_key, played_at, user_id) VALUES(?, ?, ?, ?)",
                             (row["id"], row["album_key"], min(when, now), user.id))
                if self.scrobbler:
                    self.scrobbler.queue(user.id, row["id"], min(when, now))
                self.on_played(user.id, row["id"])
        return {}

    def m_getNowPlaying(self, p, user):
        now = time.time()
        entries = []
        with self.db() as conn:
            ctx = self._ctx(conn, user.id)
            for uid, np in list(self.now_playing.items()):
                if now - np["at"] > NOW_PLAYING_FOR:
                    self.now_playing.pop(uid, None)
                    continue
                who = conn.execute("SELECT username, share_activity FROM users WHERE id = ?", (uid,)).fetchone()
                if not who or not (uid == user.id or who["share_activity"]):
                    continue
                if podcasts.is_episode(np["track"]):
                    found = podcasts.episode(conn, np["track"])
                    item = self.episode(found[0], found[1]) if found else None
                else:
                    row = conn.execute(f"{TRACKS} WHERE t.id = ?", (np["track"],)).fetchone()
                    item = self.song(row, ctx) if row else None
                if item:
                    entries.append({**item, "username": who["username"], "minutesAgo": int((now - np["at"]) // 60),
                                    "playerId": 1, "playerName": np["player"], **self.now_playing_extra(np, now)})
        return {"nowPlaying": {"entry": entries}}

    def m_getPlayQueue(self, p, user):
        with self.db() as conn:
            saved = json.loads(get_meta(conn, f"subsonic_queue:{user.id}") or "null")
            if not saved:
                return {"playQueue": {}}
            ids = [i for i in saved["ids"] if i.isdigit()]
            rows = {r["id"]: r for r in conn.execute(f"{TRACKS} WHERE t.id IN ({','.join('?' * len(ids))})", [int(i) for i in ids])} if ids else {}
            ctx = self._ctx(conn, user.id)
        return {"playQueue": {"current": saved.get("current"), "position": saved.get("position", 0),
                              "username": user.username, "changed": iso(saved["at"]), "changedBy": saved.get("by"),
                              "entry": [self.song(rows[int(i)], ctx) for i in ids if int(i) in rows]}}

    def m_savePlayQueue(self, p, user):
        with self.db() as conn:
            ids = p.all("id")[:2000]
            current = p.get("current")
            set_meta(conn, f"subsonic_queue:{user.id}", json.dumps({
                "ids": ids, "current": current, "index": ids.index(current) if current in ids else None,
                "position": p.int("position", 0), "at": time.time(), "by": p.get("c") or "app"}))
        return {}

    def m_getLyrics(self, p, user):
        artist, title = p.get("artist") or "", p.get("title") or ""
        with self.db() as conn:
            rows = conn.execute(f"{TRACKS} WHERE t.title = ? COLLATE NOCASE", (title,)).fetchall()
        row = next((r for r in rows if not artist or credits.credited(r["artist"], artist)), None)
        if not row:
            return {"lyrics": {}}
        got = lyrics.lyrics_for(self.cfg.db_path, row, self.cfg.online_lyrics)
        text = got.get("text") or "\n".join(line["text"] for line in got.get("lines") or [])
        return {"lyrics": {"artist": row["artist"], "title": row["title"], "value": text or None}}

    def m_getLyricsBySongId(self, p, user):
        with self.db() as conn:
            row = self._track_row(conn, p.need("id"))
        got = lyrics.lyrics_for(self.cfg.db_path, row, self.cfg.online_lyrics)
        base = {"displayArtist": row["artist"], "displayTitle": row["title"], "lang": "und", "offset": 0}
        if got.get("lines"):
            return {"lyricsList": {"structuredLyrics": [{**base, "synced": True, "line": [
                {"start": int(line["t"] * 1000), "value": line["text"]} for line in got["lines"]]}]}}
        if got.get("text"):
            return {"lyricsList": {"structuredLyrics": [{**base, "synced": False, "line": [
                {"value": line} for line in got["text"].split("\n")]}]}}
        return {"lyricsList": {}}

    # things Shelf doesn't have: empty answers, so apps carry on

    def m_getBookmarks(self, p, user):
        """Bookmarks are Shelf's places in long tracks (resume.py), in milliseconds."""
        with self.db() as conn:
            marks = resume.all_for(conn, user.id)
        if not marks:
            return {"bookmarks": {}}
        ids = [m["track_id"] for m in marks]
        songs = {s["id"]: s for s in self._songs(user, f"WHERE t.id IN ({','.join('?' * len(ids))})", tuple(ids), "t.id", len(ids))}
        out = [{"position": int(m["position"] * 1000), "username": user.username, "comment": m["comment"] or "",
                "created": iso(m["updated_at"]), "changed": iso(m["updated_at"]), "entry": songs[str(m["track_id"])]}
               for m in marks if str(m["track_id"]) in songs]
        return {"bookmarks": {"bookmark": out}}

    def m_createBookmark(self, p, user):
        with self.db() as conn:
            row = self._track_row(conn, p.need("id"))
            resume.put(conn, user.id, row["id"], p.int("position", 0) / 1000, row["duration"] or 0, p.get("comment"))
        return {}

    def m_deleteBookmark(self, p, user):
        with self.db() as conn:
            resume.forget(conn, user.id, self._track_row(conn, p.need("id"))["id"])
        return {}

    def m_getVideos(self, p, user):
        return {"videos": {}}


    # files (these answer with the file itself)

    def file_for(self, tid: str):
        with self.db() as conn:
            row = conn.execute("SELECT path, mtime, mime, bitrate, codec FROM tracks WHERE id = ?",
                               (int(tid),)).fetchone() if tid.isdigit() else None
        if not row or not Path(row["path"]).is_file():
            raise not_found("Song not found")
        return row

    async def stream(self, p: Params, download: bool = False, range_header: str | None = None) -> Response:
        """The file itself, or a conversion: to the format the app asks for (mp3, opus, aac, flac),
        down to its maxBitRate, from timeOffset seconds in. Podcast episodes come from their host."""
        sid = p.need("id")
        if self.episode_num(sid) is not None:
            return await self.episode_stream(sid, range_header)
        row = self.file_for(sid)
        path = Path(row["path"])
        mime = row["mime"] or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        limit = p.int("maxBitRate", 0)
        kbps = (row["bitrate"] or 0) // 1000
        fmt = (p.get("format") or "").lower()
        want = transcode.live_codec(fmt) if fmt and fmt != "raw" else None
        own = transcode.live_codec(row["codec"] or path.suffix.lstrip("."))
        same = want is None or want == own
        try:
            offset = max(0.0, float(p.get("timeOffset") or 0))
        except ValueError:
            offset = 0.0
        if download or fmt == "raw" or (not offset and same and (not limit or not kbps or kbps <= limit or want == "flac")):
            return FileResponse(path, media_type=mime, headers={**CORS, "Cache-Control": "private, max-age=86400"},
                                filename=path.name if download else None)
        codec = (want or own or "aac") if offset and same else (want or "aac")  # starting later: the same format, from there
        if codec != "aac" or offset:  # made as it's sent
            rate = min(limit, 320) if limit else transcode.LIVE[codec][3]
            return await self.live_response(path, codec, rate, offset)
        limit = limit or transcode.QUALITIES["high"]
        tier = max((q for q in transcode.QUALITIES.values() if q <= limit), default=min(transcode.QUALITIES.values()))
        out = transcode.cached(self.cfg.transcode_dir, path, row["mtime"], tier)
        if out:
            return FileResponse(out, media_type="audio/mp4", headers={**CORS, "Cache-Control": "private, max-age=86400"})
        gen = transcode.stream_transcode(self.cfg.transcode_dir, path, row["mtime"], tier, self.cfg.transcode_cache_mb)
        try:
            first = await gen.__anext__()
        except (RuntimeError, StopAsyncIteration):
            raise Fail(0, "Couldn’t convert this song")

        async def body():
            yield first
            try:
                async for chunk in gen:
                    yield chunk
            except RuntimeError:
                pass

        return StreamingResponse(body(), media_type="audio/mp4", headers={**CORS, "Cache-Control": "no-store"})

    def cover(self, p: Params) -> Response:
        cid = p.need("id")
        size = p.int("size", 600, 32, 2000)
        if cid.startswith("pc-") or self.episode_num(cid) is not None:
            path = self.show_cover_path(cid, size)
            if not path:
                raise not_found("No cover")
            return FileResponse(path, media_type="image/webp", headers={**CORS, "Cache-Control": "private, max-age=2592000"})
        with self.db() as conn:
            if cid.startswith("ar-"):
                name = artist_name(cid)
                photo = artist_info.image_path(self.cfg.data_dir, name) if name else None
                if photo and photo.is_file():
                    return FileResponse(photo, media_type="image/webp", headers={**CORS, "Cache-Control": "private, max-age=604800"})
                a = self._find_artist(conn, cid)
                with_cover = [r for r in a["albums"] if r["cover_src"]]
                src = max(with_cover, key=lambda r: r["track_count"])["cover_src"] if with_cover else None
            elif cid.startswith("al-"):
                src = self._album_row(conn, cid)["cover_src"]
            elif cid.isdigit():
                src = self._track_row(conn, cid)["cover_src"]
            else:
                raise not_found("No cover")
        path = covers.get_cover(self.cfg.cover_dir, src, size) if src else None
        if not path:
            raise not_found("No cover")
        return FileResponse(path, media_type="image/webp", headers={**CORS, "Cache-Control": "private, max-age=2592000"})


FILE_METHODS = {"stream", "download", "getCoverArt", "getAvatar", "getTranscodeStream"}
OPEN_METHODS = {"getOpenSubsonicExtensions"}


def mount(app, api: Subsonic) -> None:
    @app.api_route("/rest/{method}", methods=["GET", "POST", "OPTIONS"], include_in_schema=False)
    async def rest(method: str, request: Request):
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=CORS)
        method = method.removesuffix(".view")
        items = list(request.query_params.multi_items())
        kind = request.headers.get("content-type") or ""
        body_json = None
        if request.method == "POST" and "x-www-form-urlencoded" in kind:
            body = await request.body()
            items += urllib.parse.parse_qsl(body[:1_000_000].decode("utf-8", "replace"), keep_blank_values=True)
        elif request.method == "POST" and method == "getTranscodeDecision":  # the app's abilities, as JSON
            try:
                body_json = json.loads((await request.body())[:1_000_000] or b"null")
            except ValueError:
                body_json = None
        p = Params(items)
        p.body = body_json
        BASE_URL.set(str(request.base_url).rstrip("/"))
        try:
            user = None
            if method not in OPEN_METHODS:
                # Signed in by a trusted reverse proxy (proxyauth.py), when the app sends nothing itself.
                if api.proxy_user and p.get("u") is None and p.get("apiKey") is None:
                    user = await asyncio.to_thread(api.proxy_user, request)
                if user is None:
                    user = await asyncio.to_thread(api.sign_in, p, request.client.host if request.client else "?")
                api.set_user(user)
            if method in ("stream", "download"):
                return await api.stream(p, download=method == "download", range_header=request.headers.get("range"))
            if method == "getCoverArt":
                return await asyncio.to_thread(api.cover, p)
            if method == "getTranscodeStream":
                return await api.transcode_stream(p)
            if method == "getAvatar":
                return await asyncio.to_thread(api.m_getAvatar, p, user)
            # Off the event loop: some calls read a lot, and a few wait on the internet (podcasts).
            return answer(p, await asyncio.to_thread(api.call, method, p, user, request))
        except Fail as f:
            return answer(p, fail=f)
