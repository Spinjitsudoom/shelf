"""HTTP API and static web app."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import re
import subprocess
import urllib.error
import urllib.parse
import logging
import threading
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request, Response, WebSocket
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Literal

from . import procs
from . import analysis, backups, coverfix, covers, health, smart, subsonic, credits, feedback, genres, lastfm, updates, dj, folders, local_llm, loudness, fingerprint, follows, home as home_rows, lossy, lyrics, imports, webhooks, mixes, moods, party, peaks, playlist_maker, podcasts, releases, requests as wishlist, resume, ripper, secure, shares, scrobble, sound, stats, together, transcode, uploads, videos, watch
from . import artists as artist_info
from . import subsonic_more
from .connect import Hub, same_origin
from . import __version__
from .auth import COOKIE, MAX_AGE, Auth, User, check_username, token_from
from .config import Config
from .db import get_meta, init_db, session, set_meta
from .scanner import scan, warm_covers
from . import scanner as scanner_mod

log = logging.getLogger("shelf")
WEB_DIR = Path(__file__).parent / "web"

# Containers every current browser (incl. iOS Safari) plays natively.
NATIVE_MIMES = {"audio/mpeg", "audio/flac", "audio/mp4", "audio/aac", "audio/wav", "audio/ogg"}


class ScanManager:
    """Runs library scans on a background thread: at startup, on a timer, or on request."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.state = {"running": False, "measuring": False, "processed": 0, "last": None, "error": None}
        self.on_scanned = None  # (result, started): after a scan that changed something (webhooks)

    def start(self) -> None:
        threading.Thread(target=self._loop, name="shelf-scanner", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def trigger(self) -> None:
        self._wake.set()

    def _progress(self, n: int) -> None:
        self.state["processed"] = n

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.run_once()
            self._wake.wait(timeout=max(1, self.cfg.scan_interval_minutes) * 60)
            self._wake.clear()

    def run_once(self) -> None:
        if not self._lock.acquire(blocking=False):
            return
        self.state.update(running=True, processed=0, error=None)
        try:
            started = time.time()
            result = scan(self.cfg, progress=self._progress)
            log.info(
                "Scan: +%d ~%d -%d, %d tracks / %d albums in %ss",
                result.added, result.updated, result.removed, result.tracks, result.albums, result.seconds,
            )
            if result.failed:
                log.warning("Could not read %d files, e.g. %s", len(result.failed), result.failed[:3])
            warm_covers(self.cfg)
            self.state["last"] = {
                "added": result.added, "updated": result.updated, "removed": result.removed,
                "failed": len(result.failed), "seconds": result.seconds, "finishedAt": time.time(),
                "failedFiles": result.failed[:500],  # every scan tries them again, so this is all of them
            }
            self.state["running"] = False
            if self.on_scanned and (result.added or result.updated or result.removed):
                try:
                    self.on_scanned(result, started)
                except Exception:
                    log.exception("After-scan news failed")
            # Measure loudness for volume normalization (slow, so it runs after the scan is done).
            self.state["measuring"] = True
            loudness.analyze_pending(self.cfg.db_path, stop=self._stop)
            # Lossless files made from an MP3 or AAC, for Library health (quick: half a minute of each).
            lossy.check_pending(self.cfg.db_path, stop=self._stop)
            # The same recording under other names, by its sound, for Library health.
            fingerprint.check_pending(self.cfg.db_path, stop=self._stop)
            # Tempo and key (slower still), for playlist columns and recommendations.
            if self.cfg.analyze_tempo:  # Essentia, or Shelf's own engine where it's missing (Windows)
                analysis.analyze_pending(self.cfg.db_path, stop=self._stop)
                # How each song sounds, for "sounds like" in recommendations, radio and mixes.
                sound.analyze_pending(self.cfg.db_path, stop=self._stop)
        except Exception as e:  # keep the scanner thread alive
            log.exception("Scan failed")
            self.state["error"] = str(e)
        finally:
            self.state["running"] = False
            self.state["measuring"] = False
            self._lock.release()


# ---------- serialization ----------

def _cover_version(cover_src: str | None) -> str | None:
    return hashlib.sha1(cover_src.encode()).hexdigest()[:10] if cover_src else None


def album_json(r) -> dict:
    return {
        "id": r["id"],
        "title": r["title"],
        "artist": r["artist"],
        "artists": credits.names(r["artist"]),
        "year": r["year"],
        "genre": r["genre"],
        "trackCount": r["track_count"],
        "duration": round(r["duration"], 1),
        "color": r["color"] or None,
        "cover": _cover_version(r["cover_src"]),
        "addedAt": r["added_at"],
        "lastPlayed": r["last_played"] if "last_played" in r.keys() else None,
    }


def track_json(r) -> dict:
    return {
        "id": r["id"],
        "title": r["title"],
        "artist": r["artist"],
        "artists": credits.names(r["artist"]),
        "album": r["album_title"] if "album_title" in r.keys() else r["album"],
        "albumId": r["album_id"],
        "albumArtist": r["album_artist_name"] if "album_artist_name" in r.keys() else None,
        "albumArtists": credits.names(r["album_artist_name"]) if "album_artist_name" in r.keys() else None,
        "cover": _cover_version(r["cover_src"]) if "cover_src" in r.keys() else None,
        "trackNo": r["track_no"],
        "discNo": r["disc_no"],
        "duration": round(r["duration"], 2),
        "codec": r["codec"],
        "mime": r["mime"],
        "bitrate": r["bitrate"],
        "sampleRate": r["sample_rate"],
        "bits": r["bits"],
        "lufs": r["lufs"],
        "peak": r["peak"],
        "bpm": round(r["bpm"]) if r["bpm"] else None,
        "key": r["musical_key"],
        "camelot": analysis.camelot(r["musical_key"]),
        "mix": json.loads(r["mix_points"]) if "mix_points" in r.keys() and r["mix_points"] else None,
    }


def _artist_count(conn) -> int:
    """How many artists have albums, each artist of a shared album counted once."""
    return len({videos.fold(n) for (a,) in conn.execute("SELECT artist FROM albums") for n in credits.names(a)})


def album_loudness(tracks) -> tuple[float | None, float | None]:
    """Album loudness: the duration-weighted energy average of its tracks, and the loudest peak."""
    measured = [t for t in tracks if t["lufs"] is not None and t["duration"]]
    if not measured:
        return None, None
    import math
    energy = sum(t["duration"] * 10 ** (t["lufs"] / 10) for t in measured)
    lufs = 10 * math.log10(energy / sum(t["duration"] for t in measured))
    peaks = [t["peak"] for t in measured if t["peak"] is not None]
    return round(lufs, 2), (max(peaks) if peaks else None)


TRACK_SELECT = """
    SELECT t.*, a.id AS album_id, a.title AS album_title, a.artist AS album_artist_name, a.cover_src
    FROM tracks t JOIN albums a ON a.key = t.album_key
"""
TRACK_ORDER = "ORDER BY COALESCE(t.disc_no, 1), COALESCE(t.track_no, 9999), t.path"

ALBUM_SORTS = {
    "artist": "artist COLLATE NOCASE, COALESCE(year, 9999), title COLLATE NOCASE",
    "title": "title COLLATE NOCASE",
    "year": "COALESCE(year, 0) DESC, artist COLLATE NOCASE",
    "added": "added_at DESC, artist COLLATE NOCASE, year",
    "random": "RANDOM()",
    # played or added most recently first, like a library's "Recents"
    "recent": "MAX(COALESCE(last_played, 0), added_at) DESC, title COLLATE NOCASE",
}


class PlaylistBody(BaseModel):
    name: str | None = Field(None, max_length=200)
    description: str | None = Field(None, max_length=2000)
    trackIds: list[int] = Field(default_factory=list, max_length=5000)
    mix: bool | None = None
    shared: int | None = Field(None, ge=0, le=2)  # 0 private, 1 public, 2 collaborative
    rules: dict | None = None  # a smart playlist's rules (smart.py)


class WebhookBody(BaseModel):
    url: str = Field(..., max_length=2000)
    events: list[str] = Field(default_factory=list, max_length=10)
    secret: str | None = Field(None, max_length=200)


class ImportBody(BaseModel):
    text: str = Field("", max_length=8_000_000)  # a file's contents, a pasted list, or a link
    filename: str = Field("", max_length=300)


TRANSITIONS = ("auto", "blend", "swap", "rise", "sweep", "fade", "cut")
VOLUME_CURVES = ("smooth", "dj", "quick", "cut")
EQ_MOVES = ("none", "swap", "kill")
FILTER_MOVES = ("none", "rise", "wash", "sweep")


def _choice(options):
    return "^(" + "|".join(options) + ")$"


class FolderBody(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    replace: str | None = Field(None, max_length=4096)  # change this folder to `path`


class TransitionBody(BaseModel):
    """A preset, optionally with its parts changed in the transition editor."""
    style: str = Field(pattern=_choice(TRANSITIONS))
    volume: str | None = Field(None, pattern=_choice(VOLUME_CURVES))
    eq: str | None = Field(None, pattern=_choice(EQ_MOVES))
    filter: str | None = Field(None, pattern=_choice(FILTER_MOVES))
    bars: float | None = Field(None, ge=0.5, le=32)  # length, beat-matched
    seconds: float | None = Field(None, ge=1, le=30)  # length, not beat-matched
    shift: float | None = Field(None, ge=-64, le=16)  # start moved by this many bars (or seconds)

    def stored(self) -> str | None:
        extra = {k: v for k, v in self.model_dump().items() if k != "style" and v is not None}
        if not extra:
            return None if self.style == "auto" else self.style
        return json.dumps({"preset": self.style, **extra})


def transition_json(raw: str | None) -> dict:
    """A stored transition ("swap", or JSON from the editor) as {"preset": ..., ...}."""
    if not raw:
        return {"preset": "auto"}
    if raw.startswith("{"):
        try:
            return json.loads(raw)
        except ValueError:
            return {"preset": "auto"}
    return {"preset": raw}


class WatchBody(BaseModel):
    path: str = Field(max_length=1000)


class ShareBody(BaseModel):
    kind: Literal["track", "album", "playlist"]
    id: int
    days: Literal[1, 7, 30] | None = 7  # None: never runs out


class SharingBody(BaseModel):
    enabled: bool


MBID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"


class RequestBody(BaseModel):
    artist: str = Field(max_length=300)
    album: str | None = Field(None, max_length=300)
    note: str | None = Field(None, max_length=1000)
    # Picked from MusicBrainz's suggestions:
    artistId: str | None = Field(None, pattern=MBID_PATTERN)
    albumId: str | None = Field(None, pattern=MBID_PATTERN)
    year: int | None = Field(None, ge=1000, le=3000)
    type: str | None = Field(None, max_length=40)


class PodcastBody(BaseModel):
    feedUrl: str = Field(..., min_length=8, max_length=2000)


class EpisodeBody(BaseModel):
    finished: bool


class HomeUsedBody(BaseModel):
    row: str = Field(..., min_length=1, max_length=240)


class RequestStatusBody(BaseModel):
    status: Literal["open", "done", "declined"]


class SecureBody(BaseModel):
    url: str | None = Field(None, max_length=300)


class FunnelBody(BaseModel):
    on: bool


class ClaimBody(BaseModel):
    code: str = Field(max_length=100)


class ResumeBody(BaseModel):
    position: float = Field(ge=0, le=7 * 86400)


class BackupFolderBody(BaseModel):
    folder: str = Field(max_length=1000)


class ApiKeyBody(BaseModel):
    name: str = Field("App", max_length=80)


class LastfmKeysBody(BaseModel):
    key: str = Field(max_length=100)
    secret: str = Field(max_length=100)


class AutoUpdateBody(BaseModel):
    enabled: bool


class MakeBody(BaseModel):
    """A playlist from a few words."""
    prompt: str = Field(min_length=1, max_length=200)
    size: int = Field(30, ge=1, le=100)


class SuggestBody(BaseModel):
    """Songs to suggest for: those like `trackIds`, leaving out `exclude`."""
    trackIds: list[int] = Field(max_length=5000)
    exclude: list[int] = Field(default_factory=list, max_length=10000)
    seed: int = 0
    limit: int = Field(10, ge=1, le=100)


class PlaylistAdd(BaseModel):
    trackIds: list[int] = Field(max_length=5000)
    suggested: bool = False  # from the playlist's suggestions (taking them back out teaches them)


class PlaylistOrder(BaseModel):
    entryIds: list[int] = Field(max_length=10000)


class LoginBody(BaseModel):
    username: str = Field("admin", max_length=64)  # the account made from config.toml's password
    password: str = Field(max_length=256)


class SetupBody(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)


class UserCreate(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)
    admin: bool = False


class UserPatch(BaseModel):
    username: str | None = Field(None, max_length=64)
    password: str | None = Field(None, max_length=256)
    admin: bool | None = None


class DJSettings(BaseModel):
    provider: str | None = Field(None, max_length=20)
    key: str | None = Field(None, max_length=400)  # "" removes it
    model: str | None = Field(None, max_length=100)
    voice: str | None = Field(None, max_length=40)
    speed: float | None = Field(None, ge=0.7, le=1.4)
    expressive: float | None = Field(None, ge=0.2, le=1.0)  # the natural voice: calm 0.35 .. animated 0.85
    cohost: str | None = Field(None, max_length=40)  # a second host's voice for the breaks; "" for none
    say: str | None = Field(None, max_length=5000)  # "Name = how to say it" lines
    enabled: bool | None = None  # the DJ is experimental: off until an admin turns it on


class DJNext(BaseModel):
    exclude: list[int] = Field(default_factory=list, max_length=5000)
    first: bool = False
    previous: int | None = None  # the song playing before this set starts, to back-announce
    when: str = Field("", max_length=60)  # the listener's local day (and time), e.g. "Saturday 9:20 PM"
    hour: int = Field(12, ge=0, le=23)
    minute: int | None = Field(None, ge=0, le=59)  # None: don't give a time (an opening made ahead)


class DJFeedback(BaseModel):
    kind: str = Field(pattern="^(skip|switch|up|down)$")
    track: int | None = None
    theme: str | None = Field(None, max_length=20)
    text: str | None = Field(None, max_length=600)  # up/down: the line


class DJRequest(BaseModel):
    text: str = Field(min_length=2, max_length=200)
    previous: int | None = None
    exclude: list[int] = Field(default_factory=list, max_length=5000)
    when: str = Field("", max_length=60)
    hour: int = Field(12, ge=0, le=23)
    minute: int | None = Field(None, ge=0, le=59)


class DJLink(BaseModel):
    previous: int
    next: int
    when: str = Field("", max_length=60)
    hour: int = Field(12, ge=0, le=23)


class RipBody(BaseModel):
    artist: str = Field(max_length=300)
    album: str = Field(max_length=300)
    year: str | None = Field(None, max_length=10)
    titles: list[str] = Field(max_length=99)
    disc: int | None = Field(None, ge=1, le=99)
    folder: str | None = Field(None, max_length=4096)


class MeBody(BaseModel):
    shareActivity: bool | None = None
    listenbrainzToken: str | None = Field(None, max_length=200)  # "" disconnects


class PasswordBody(BaseModel):
    current: str = Field(max_length=256)
    new: str = Field(max_length=256)


# Who the request is from (set by the sign-in check for every /api/ request).
CURRENT: ContextVar[User | None] = ContextVar("shelf_user", default=None)
OPEN_PATHS = {"/api/session", "/api/login", "/api/setup", "/api/ping", "/api/session/claim"}


def me() -> User:
    user = CURRENT.get()
    if user is None:
        raise HTTPException(401, "Not signed in")
    return user


def uid() -> int:
    return me().id


def admin_only() -> User:
    user = me()
    if not user.admin:
        raise HTTPException(403, "Only an admin can do that")
    return user


def create_app(cfg: Config, start_scanner: bool = True) -> FastAPI:
    cfg.prepare()
    init_db(cfg.db_path)
    with session(cfg.db_path) as conn:
        credits.refresh(conn)
    # Folders changed in Settings win over config.toml (but not over SHELF_MUSIC_DIRS).
    saved = None if folders.locked() else folders.load_saved(cfg.db_path)
    if saved is not None:
        cfg.music_dirs = saved
    auth = Auth(cfg.db_path, cfg.secret_key, cfg.password)
    scanner = ScanManager(cfg)
    scrobbler = scrobble.Scrobbler(cfg.db_path)
    new_releases = releases.Releases(cfg.db_path, enabled=cfg.artist_info)
    podcast_checker = podcasts.Refresher(cfg.db_path)
    listening = {"at": 0.0}

    def last_listening() -> float:
        """When music last played here: now, if a device is playing; else the latest play."""
        now = time.time()
        if any(h.state and h.state.get("playing") and h.active in h.devices for h in list(hubs.values())):
            listening["at"] = now
        with session(cfg.db_path) as conn:
            last = conn.execute("SELECT MAX(played_at) FROM plays").fetchone()[0] or 0.0
        return max(listening["at"], last)

    new_version = updates.Updates(enabled=cfg.check_updates, db_path=cfg.db_path, idle_since=last_listening)
    cd = ripper.Ripper(on_done=scanner.trigger)
    dj_voice = dj.Voice(Path(os.environ.get("SHELF_TTS_DIR") or cfg.data_dir / "tts"), cfg.data_dir / "dj-voice")
    natural = dj.Chatterbox(Path(os.environ.get("SHELF_CHATTERBOX_DIR") or cfg.data_dir / "tts-chatterbox"))
    dj_voice.natural = natural
    dj_sessions: dict[int, dict] = {}  # per person: themes and artists used so far
    dj_prepared: dict[int, dict] = {}  # per person: an opening made ahead, so the DJ starts at once
    llm = local_llm.LocalLLM(cfg.data_dir / "llm")
    dj.local_writer = llm

    @asynccontextmanager
    async def lifespan(_app):
        if not cfg.music_dirs:
            log.warning("No music folders yet; add them in Settings (or music_dirs in config.toml)")
        if not auth.has_users():
            log.warning("No accounts yet: open Shelf in a browser and create the admin account")
        if start_scanner:
            scanner.start()
            scrobbler.start()
            watcher.start()
            saved_copies.start()
            new_releases.start()
            new_version.start()
            podcast_checker.start()
        yield
        new_version.stop()
        scanner.stop()
        scrobbler.stop()
        watcher.stop()
        saved_copies.stop()
        new_releases.stop()
        podcast_checker.stop()
        dj_voice.stop()
        natural.stop()
        llm.stop()

    app = FastAPI(title="Shelf", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.scanner = scanner
    hooks = app.state.webhooks = webhooks.Sender(lambda: session(cfg.db_path))

    def _tell_library(result, started: float) -> None:
        with session(cfg.db_path) as conn:
            wishlist.fulfil(conn)  # requests the new music answers are done now
            new = conn.execute("SELECT title, artist FROM albums WHERE added_at >= ? ORDER BY artist, title LIMIT 20",
                               (started,)).fetchall()
        hooks.emit("library", {"added": result.added, "updated": result.updated, "removed": result.removed,
                               "albums": [{"title": r["title"], "artist": r["artist"]} for r in new]})

    scanner.on_scanned = _tell_library

    def _tell_played(user_id: int, track_id: int) -> None:
        with session(cfg.db_path) as conn:
            row = conn.execute(f"{TRACK_SELECT} WHERE t.id = ?", (track_id,)).fetchone()
        if row:
            hooks.emit("played", {"track": webhooks.track_json(row)}, user_id)

    def _watch_dir() -> Path | None:
        with session(cfg.db_path) as conn:
            p = get_meta(conn, "watch_dir")
        return Path(p) if p else None

    watcher = watch.Watcher(_watch_dir, lambda: cfg.music_dirs[0] if cfg.music_dirs else None,
                            on_filed=lambda n: scanner.trigger())
    def _backup_dir() -> Path:
        with session(cfg.db_path) as conn:
            p = get_meta(conn, "backup_dir")
        return Path(p) if p else cfg.data_dir / "backups"

    saved_copies = backups.Backups(cfg.db_path, _backup_dir)
    app.state.backups = saved_copies
    app.state.scrobbler = scrobbler
    app.state.cfg = cfg
    hubs: dict[int, Hub] = {}  # Connect: each person's devices only see each other
    app.state.hubs = hubs

    def db():
        return session(cfg.db_path)

    app.state.slow_after = 3.0  # seconds: slower requests are named in the log
    with db() as conn:
        app.state.secure_url = secure.get_url(conn)  # the https address everyone should use, if any
    handoffs = secure.Handoffs()

    @app.middleware("http")
    async def timed(request: Request, call_next):
        """Name slow requests in the log, so a page that hangs can be traced to what it waited on."""
        start = time.monotonic()
        response = await call_next(request)
        took = time.monotonic() - start
        if took >= app.state.slow_after and not request.url.path.startswith("/api/stream"):
            log.warning("Slow request: %s %s took %.1f s", request.method, request.url.path, took)
        return response

    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        if request.method in ("GET", "HEAD") and not path.startswith(("/api/", "/rest/")):
            # The sign-in page over plain http from the internet: to the secure address, so the
            # password isn't typed in the clear. (Signed in, the web app moves itself, sign-in and all.)
            to = secure.redirect_for(request.url.scheme, request.headers.get("host", ""), path,
                                     request.url.query, app.state.secure_url)
            if to and "ShelfAndroid/" not in request.headers.get("user-agent", "") \
                    and auth.user_for(token_from(request.headers, request.cookies)) is None:  # Shelf Lite moves itself
                return RedirectResponse(to, status_code=307)
        if path.startswith("/api/") and path not in OPEN_PATHS:
            user = auth.user_for(token_from(request.headers, request.cookies))
            if user is None:
                return JSONResponse({"detail": "Not signed in"}, status_code=401)
            CURRENT.set(user)
        response = await call_next(request)
        if not path.startswith("/api/"):
            # App shell: always revalidate so updates show up right away.
            response.headers.setdefault("Cache-Control", "no-cache")
        return response

    # ---------- session ----------

    def _signed_in(request: Request, response: Response, user: User) -> dict:
        token = auth.make_token(user)
        response.set_cookie(
            COOKIE, token, max_age=MAX_AGE, httponly=True, samesite="lax",
            secure=request.url.scheme == "https",
        )
        return {"ok": True, "user": user.json(), "token": token}

    def _client(request: Request) -> str:
        return request.client.host if request.client else "?"

    @app.get("/api/ping")
    def ping(response: Response):
        """Lets a sign-in screen on another address check this is a Shelf server."""
        response.headers["Access-Control-Allow-Origin"] = "*"
        return {"app": "shelf", "version": __version__}

    def _sharing_on() -> bool:
        with db() as conn:
            return shares.enabled(conn)

    def _me_json(user: User) -> dict:
        with db() as conn:
            r = conn.execute("SELECT share_activity, listenbrainz_user, listenbrainz_token, lastfm_user, lastfm_session, subsonic_secret FROM users WHERE id = ?",
                             (user.id,)).fetchone()
        return user.json() | {"shareActivity": bool(r["share_activity"]) if r else True,
                              "listenbrainz": (r["listenbrainz_user"] or "ListenBrainz") if r and r["listenbrainz_token"] else None,
                              "lastfm": (r["lastfm_user"] or "Last.fm") if r and r["lastfm_session"] else None,
                              "lastfmAvailable": lastfm.keys(cfg.db_path) is not None,
                              "subsonic": bool(r and r["subsonic_secret"]),
                              "shareLinks": _sharing_on()}

    @app.get("/api/session")
    def get_session(request: Request):
        user = auth.user_for(token_from(request.headers, request.cookies))
        return {"setup": not auth.has_users(), "signedIn": user is not None,
                "user": _me_json(user) if user else None, "version": __version__,
                "secureUrl": app.state.secure_url,
                "features": {"dj": _dj_on() if user else False}}

    @app.post("/api/session/handoff")
    def session_handoff():
        """A one-time code that signs this person in on the secure address (see secure.py)."""
        return {"code": handoffs.make(me().id)}

    @app.post("/api/session/claim")
    def session_claim(body: ClaimBody, request: Request, response: Response):
        uid = handoffs.claim(body.code)
        user = auth.get(uid) if uid is not None else None
        if user is None:
            raise HTTPException(401, "That sign-in has run out. Sign in again.")
        return _signed_in(request, response, user)

    @app.patch("/api/me")
    def edit_me(body: MeBody):
        user = me()
        if body.shareActivity is not None:
            with db() as conn:
                conn.execute("UPDATE users SET share_activity = ? WHERE id = ?", (int(body.shareActivity), user.id))
        if body.listenbrainzToken is not None:
            token = body.listenbrainzToken.strip()
            name = None
            if token:
                try:
                    name = scrobble.check_token(token)
                except ValueError as e:
                    raise HTTPException(400, str(e)) from e
            with db() as conn:
                conn.execute("UPDATE users SET listenbrainz_token = ?, listenbrainz_user = ? WHERE id = ?",
                             (token or None, name, user.id))
                if not token:
                    conn.execute("DELETE FROM scrobbles WHERE user_id = ? AND service = 'listenbrainz'", (user.id,))
        return _me_json(user)

    # ---------- the watch folder ----------

    @app.patch("/api/admin/watch")
    def set_watch_folder(body: WatchBody):
        """A folder to drop music into: it's renamed from its tags and filed as Artist/Album. Empty turns it off."""
        admin_only()
        path = body.path.strip()
        if path:
            p = Path(path).expanduser()
            if not p.is_dir():
                raise HTTPException(400, "That folder doesn’t exist on the server")
            for m in cfg.music_dirs:
                if p.resolve() == m.resolve() or m.resolve() in p.resolve().parents or p.resolve() in m.resolve().parents:
                    raise HTTPException(400, "Pick a folder outside your music folders (songs are moved from it into them)")
            path = str(p)
        with db() as conn:
            set_meta(conn, "watch_dir", path)
        return {"path": path or None}

    # ---------- backups ----------

    def _backups_view() -> dict:
        return {"folder": str(_backup_dir()), "backups": saved_copies.list()}

    @app.get("/api/admin/backups")
    def list_backups():
        admin_only()
        return _backups_view()

    @app.post("/api/admin/backups")
    def back_up_now():
        admin_only()
        try:
            made = saved_copies.make()
        except OSError as e:
            raise HTTPException(500, f"Couldn’t back up: {e.strerror or e}")
        return {"name": made.name, **_backups_view()}

    @app.patch("/api/admin/backups")
    def set_backup_folder(body: BackupFolderBody):
        """Where backups go: another drive is safer. Empty puts them back in the data folder."""
        admin_only()
        path = body.folder.strip()
        if path:
            p = Path(path).expanduser()
            if not p.is_dir():
                raise HTTPException(400, "That folder doesn’t exist on the server")
            path = str(p)
        with db() as conn:
            set_meta(conn, "backup_dir", path)
        return _backups_view()

    @app.get("/api/admin/backups/{name}")
    def download_backup(name: str):
        admin_only()
        try:
            p = saved_copies.path_of(name)
        except backups.BackupError:
            raise HTTPException(404, "No such backup")
        return FileResponse(p, media_type="application/gzip", filename=name)

    @app.post("/api/admin/backups/{name}/restore")
    def restore_backup(name: str):
        """Put a backup back; what's there now is backed up first, so this can be undone."""
        admin_only()
        try:
            safety = saved_copies.restore(name)
        except backups.BackupError as e:
            raise HTTPException(400, str(e))
        return {"before": safety.name, **_backups_view()}

    # ---------- library health ----------

    cover_sizes: dict[tuple[str, float], tuple[int, int] | None] = {}

    def _cover_size(src: str) -> tuple[int, int] | None:
        """The size of an album's cover at its source (remembered until the file changes)."""
        import io

        from PIL import Image

        path = Path(src.partition(":")[2])
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return None
        if (src, mtime) not in cover_sizes:
            raw = covers._load_source_bytes(src)
            try:
                cover_sizes[(src, mtime)] = Image.open(io.BytesIO(raw)).size if raw else None
            except Exception:  # not a picture Pillow can read
                cover_sizes[(src, mtime)] = None
        return cover_sizes[(src, mtime)]

    def _use_found_cover(album: dict, data: bytes) -> None:
        coverfix.save(cfg.found_cover_dir, album["key"], data)
        with db() as conn:
            conn.execute("UPDATE albums SET cover_src = ?, color = NULL WHERE id = ?",
                         (f"file:{coverfix.override_path(cfg.found_cover_dir, album['key'])}", album["id"]))

    def _albums_without_covers() -> list[dict]:
        with db() as conn:
            return [dict(r) for r in conn.execute("SELECT id, key, title, artist FROM albums WHERE cover_src IS NULL")]

    cover_finder = coverfix.Finder(_albums_without_covers, _use_found_cover)
    app.state.cover_finder = cover_finder

    # ---------- webhooks ----------

    @app.get("/api/admin/webhooks")
    def list_webhooks():
        admin_only()
        with db() as conn:
            rows = conn.execute("SELECT * FROM webhooks ORDER BY id").fetchall()
        return {"hooks": [webhooks.hook_json(r) for r in rows], "events": webhooks.EVENTS}

    @app.post("/api/admin/webhooks")
    def add_webhook(body: WebhookBody):
        me_user = admin_only()
        try:
            url, events = webhooks.check_url(body.url), webhooks.check_events(body.events)
        except ValueError as e:
            raise HTTPException(400, str(e))
        with db() as conn:
            hid = conn.execute("INSERT INTO webhooks(user_id, url, events, secret, created_at) VALUES(?, ?, ?, ?, ?)",
                               (me_user.id, url, json.dumps(events), (body.secret or "").strip(), time.time())).lastrowid
            return webhooks.hook_json(conn.execute("SELECT * FROM webhooks WHERE id = ?", (hid,)).fetchone())

    @app.delete("/api/admin/webhooks/{hook_id}")
    def remove_webhook(hook_id: int):
        admin_only()
        with db() as conn:
            conn.execute("DELETE FROM webhooks WHERE id = ?", (hook_id,))
        return {"ok": True}

    @app.post("/api/admin/webhooks/{hook_id}/test")
    def test_webhook(hook_id: int):
        """Sends a test message straight away; the answer's status, or why it didn't arrive."""
        admin_only()
        with db() as conn:
            if not conn.execute("SELECT 1 FROM webhooks WHERE id = ?", (hook_id,)).fetchone():
                raise HTTPException(404, "Webhook not found")
        return {"status": hooks.send_now(hook_id)}

    @app.get("/api/admin/health")
    def library_health():
        """What's missing or wrong on the shelf; nothing is changed by looking."""
        admin_only()
        unreadable = (scanner.state.get("last") or {}).get("failedFiles", [])
        with db() as conn:
            found = health.report(conn, _cover_size, unreadable)
        return {**found, "finder": cover_finder.state}

    def _album_row(album_id: int):
        with db() as conn:
            row = conn.execute("SELECT * FROM albums WHERE id = ?", (album_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Album not found")
        return row

    @app.post("/api/admin/covers/find-missing")
    def find_missing_covers():
        """Look for covers for every album without one (taking only close matches)."""
        admin_only()
        cover_finder.start()
        return cover_finder.state

    @app.get("/api/admin/covers/{album_id}/candidates")
    def cover_candidates(album_id: int):
        admin_only()
        row = _album_row(album_id)
        try:
            found = coverfix.candidates(row["artist"], row["title"])
        except (OSError, ValueError):
            raise HTTPException(502, "MusicBrainz can’t be reached right now")
        return [{**c, "image": f"api/releases/{c['mbid']}/cover"} for c in found]

    @app.post("/api/admin/covers/{album_id}")
    def use_cover(album_id: int, body: dict):
        """Use a release's cover from the Cover Art Archive for this album."""
        admin_only()
        row = _album_row(album_id)
        mbid = str(body.get("mbid") or "")
        if not re.fullmatch(r"[0-9a-f-]{36}", mbid):
            raise HTTPException(400, "Pick one of the covers")
        data = coverfix.download(mbid)
        if not data:
            raise HTTPException(502, "That cover couldn’t be downloaded")
        try:
            _use_found_cover(dict(row), data)
        except OSError as e:
            raise HTTPException(500, f"Couldn’t keep the cover: {e}")
        except Exception:
            raise HTTPException(502, "That cover isn’t a picture Shelf can read")
        return album_json(_album_row(album_id))

    @app.delete("/api/admin/covers/{album_id}")
    def drop_found_cover(album_id: int):
        """Go back to the album's own cover (or none)."""
        admin_only()
        row = _album_row(album_id)
        coverfix.override_path(cfg.found_cover_dir, row["key"]).unlink(missing_ok=True)
        with db() as conn:
            tracks = conn.execute("SELECT path, has_art FROM tracks WHERE album_key = ? ORDER BY COALESCE(disc_no, 1),"
                                  " COALESCE(track_no, 9999), path", (row["key"],)).fetchall()
            src = scanner_mod._pick_cover(tracks) if tracks else None
            conn.execute("UPDATE albums SET cover_src = ?, color = NULL WHERE id = ?", (src, album_id))
        return album_json(_album_row(album_id))

    # ---------- Subsonic apps ----------

    def _smart_for(conn, row, user_id: int):
        rules = _rules_of(row)
        return _smart_rows(conn, row["id"], rules, user_id) if rules else None

    sub_api = subsonic.Subsonic(cfg, auth, scrobbler=scrobbler, scanner=scanner, set_user=CURRENT.set,
                                smart_rows=lambda conn, row, user_id: _smart_for(conn, row, user_id), on_played=_tell_played,
                                remove_user=lambda user_id: _remove_account(user_id))
    subsonic.mount(app, sub_api)

    @app.get("/api/me/subsonic")
    def my_app_password():
        """The app password for Subsonic apps (Symfonium, Feishin...), if one's been made."""
        return {"username": me().username, "password": sub_api.app_password(uid())}

    @app.post("/api/me/subsonic")
    def new_app_password():
        """Make (or replace) the app password: apps using the old one have to sign in again."""
        password = subsonic.new_app_password()
        sub_api.set_app_password(uid(), password)
        return {"username": me().username, "password": password}

    @app.delete("/api/me/subsonic")
    def remove_app_password():
        sub_api.set_app_password(uid(), None)
        return {"username": me().username, "password": None}

    @app.get("/api/me/apikeys")
    def my_api_keys():
        """API keys: what apps that support them sign in with, instead of a username and password."""
        with db() as conn:
            rows = conn.execute("SELECT id, name, hint, created_at, used_at FROM api_keys WHERE user_id = ? ORDER BY created_at DESC",
                                (uid(),)).fetchall()
        return {"keys": [{"id": r["id"], "name": r["name"], "hint": r["hint"], "createdAt": r["created_at"],
                          "usedAt": r["used_at"]} for r in rows]}

    @app.post("/api/me/apikeys")
    def new_api_key(body: ApiKeyBody):
        """A new key, shown this once: Shelf keeps only a fingerprint of it."""
        with db() as conn:
            if conn.execute("SELECT COUNT(*) FROM api_keys WHERE user_id = ?", (uid(),)).fetchone()[0] >= 50:
                raise HTTPException(409, "That’s 50 keys already. Remove some you don’t use first.")
            key = subsonic_more.new_api_key(conn, uid(), body.name)
        return {"key": key, **my_api_keys()}

    @app.delete("/api/me/apikeys/{key_id}")
    def remove_api_key(key_id: int):
        with db() as conn:
            if not conn.execute("DELETE FROM api_keys WHERE id = ? AND user_id = ?", (key_id, uid())).rowcount:
                raise HTTPException(404, "No such key")
        return my_api_keys()

    # ---------- Last.fm ----------

    @app.patch("/api/admin/lastfm")
    def set_lastfm_keys(body: LastfmKeysBody):
        """The server's Last.fm API account (made at last.fm/api/account/create); empty removes it."""
        admin_only()
        with db() as conn:
            set_meta(conn, "lastfm_key", body.key.strip())
            set_meta(conn, "lastfm_secret", body.secret.strip())
        return {"configured": lastfm.keys(cfg.db_path) is not None}

    def _lastfm_account() -> tuple[str, str]:
        account = lastfm.keys(cfg.db_path)
        if not account:
            raise HTTPException(409, "An admin needs to add a Last.fm API account first (in the admin dashboard)")
        return account

    @app.post("/api/me/lastfm/start")
    def lastfm_start():
        """Step 1: a link to approve Shelf on last.fm."""
        key, secret = _lastfm_account()
        try:
            token = lastfm.call("auth.getToken", key, secret)["token"]
        except (lastfm.LastfmError, OSError) as e:
            raise HTTPException(502, f"Last.fm didn’t answer: {e}") from e
        with db() as conn:
            conn.execute("UPDATE users SET lastfm_token = ? WHERE id = ?", (token, uid()))
        return {"url": f"{lastfm.AUTH}?api_key={urllib.parse.quote(key)}&token={urllib.parse.quote(token)}"}

    @app.post("/api/me/lastfm/finish")
    def lastfm_finish():
        """Step 2, once approved on last.fm: connected."""
        key, secret = _lastfm_account()
        with db() as conn:
            token = conn.execute("SELECT lastfm_token FROM users WHERE id = ?", (uid(),)).fetchone()["lastfm_token"]
        if not token:
            raise HTTPException(409, "Start connecting Last.fm first")
        try:
            s = lastfm.call("auth.getSession", key, secret, token=token)["session"]
        except lastfm.LastfmError as e:
            raise HTTPException(409, "Approve Shelf on last.fm first, then choose Done") from e
        except OSError as e:
            raise HTTPException(502, f"Last.fm didn’t answer: {e}") from e
        with db() as conn:
            conn.execute("UPDATE users SET lastfm_session = ?, lastfm_user = ?, lastfm_token = NULL WHERE id = ?",
                         (s["key"], s["name"], uid()))
        return {"lastfm": s["name"]}

    @app.delete("/api/me/lastfm")
    def lastfm_disconnect():
        with db() as conn:
            conn.execute("UPDATE users SET lastfm_session = NULL, lastfm_user = NULL, lastfm_token = NULL WHERE id = ?", (uid(),))
            conn.execute("DELETE FROM scrobbles WHERE user_id = ? AND service = 'lastfm'", (uid(),))
        return {"lastfm": None}

    @app.post("/api/setup")
    def setup(body: SetupBody, request: Request, response: Response):
        """The very first account, made by whoever opens a new server first. It's an admin."""
        if auth.has_users():
            raise HTTPException(409, "This server already has accounts. Sign in instead.")
        try:
            user = auth.create(body.username, body.password, admin=True)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return _signed_in(request, response, user)

    @app.post("/api/login")
    def login(body: LoginBody, request: Request, response: Response):
        client = _client(request)
        if auth.locked_out(client):
            raise HTTPException(429, "Too many attempts. Try again in a few minutes.")
        user = auth.attempt(client, body.username, body.password)
        if user is None:
            time.sleep(0.5)
            raise HTTPException(401, "Wrong username or password")
        return _signed_in(request, response, user)

    @app.post("/api/logout")
    def logout(response: Response):
        response.delete_cookie(COOKIE)
        return {"ok": True}

    @app.put("/api/me/password")
    def change_my_password(body: PasswordBody, request: Request, response: Response):
        user = me()
        client = _client(request)
        if auth.locked_out(client):
            raise HTTPException(429, "Too many attempts. Try again in a few minutes.")
        if auth.attempt(client, user.username, body.current) is None:
            raise HTTPException(403, "Your current password didn’t match")
        try:
            auth.set_password(user.id, body.new)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return _signed_in(request, response, auth.get(user.id))  # this device stays signed in

    # ---------- accounts (admin) ----------

    def _users_json(conn) -> list[dict]:
        auth.flush_seen()
        rows = conn.execute(
            """SELECT u.*,
                      (SELECT COUNT(*) FROM likes l WHERE l.user_id = u.id) AS likes,
                      (SELECT COUNT(*) FROM playlists p WHERE p.user_id = u.id) AS playlists,
                      (SELECT COUNT(*) FROM plays p WHERE p.user_id = u.id) AS plays,
                      (SELECT MAX(played_at) FROM plays p WHERE p.user_id = u.id) AS last_played
               FROM users u ORDER BY u.is_admin DESC, u.username COLLATE NOCASE""").fetchall()
        return [{
            "id": r["id"], "username": r["username"], "admin": bool(r["is_admin"]),
            "createdAt": r["created_at"], "lastSeen": r["last_seen"], "lastPlayed": r["last_played"],
            "likes": r["likes"], "playlists": r["playlists"], "plays": r["plays"],
            "devices": len(hubs[r["id"]].devices) if r["id"] in hubs else 0,
        } for r in rows]

    @app.get("/api/users")
    def list_users():
        admin_only()
        with db() as conn:
            return _users_json(conn)

    @app.post("/api/users")
    def create_user(body: UserCreate):
        admin_only()
        try:
            user = auth.create(body.username, body.password, admin=body.admin)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return user.json()

    @app.patch("/api/users/{user_id}")
    def edit_user(user_id: int, body: UserPatch):
        admin_only()
        target = auth.get(user_id)
        if target is None:
            raise HTTPException(404, "No such account")
        if body.admin is False and target.admin and auth.admins() <= 1:
            raise HTTPException(409, "Shelf needs at least one admin. Make someone else an admin first.")
        try:
            with db() as conn:
                if body.username is not None:
                    name = check_username(body.username)
                    if conn.execute("SELECT 1 FROM users WHERE username = ? COLLATE NOCASE AND id != ?",
                                    (name, user_id)).fetchone():
                        raise ValueError(f"There’s already an account called {name}")
                    conn.execute("UPDATE users SET username = ? WHERE id = ?", (name, user_id))
                if body.admin is not None:
                    conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (int(body.admin), user_id))
            if body.password is not None:
                auth.set_password(user_id, body.password)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        auth.forget(user_id)
        return auth.get(user_id).json()

    @app.post("/api/users/{user_id}/signout")
    def sign_out_user(user_id: int):
        admin_only()
        if auth.get(user_id) is None:
            raise HTTPException(404, "No such account")
        auth.sign_out_everywhere(user_id)
        return {"ok": True}

    def _remove_account(user_id: int) -> None:
        with db() as conn:
            conn.execute("DELETE FROM likes WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM plays WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM playlists WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        auth.forget(user_id)

    @app.delete("/api/users/{user_id}")
    async def delete_user(user_id: int):
        admin = admin_only()
        if user_id == admin.id:
            raise HTTPException(409, "You can’t remove your own account")
        target = auth.get(user_id)
        if target is None:
            raise HTTPException(404, "No such account")
        if target.admin and auth.admins() <= 1:
            raise HTTPException(409, "Shelf needs at least one admin")
        _remove_account(user_id)
        hub = hubs.pop(user_id, None)
        if hub:
            for d in list(hub.devices.values()):
                try:
                    await d.ws.close(code=1008)
                except Exception:  # already gone
                    pass
        return {"ok": True}

    @app.get("/api/admin/signins")
    def failed_signins():
        """Addresses with recent wrong passwords, and whether they're locked out."""
        admin_only()
        return auth.failures()

    @app.delete("/api/admin/signins")
    def clear_signins(address: str | None = Query(None, max_length=200)):
        """Lift sign-in lockouts: one address, or all of them."""
        admin_only()
        return {"cleared": auth.clear_failures(address), "left": auth.failures()}

    @app.get("/api/admin/overview")
    def admin_overview():
        """The admin dashboard's numbers: the library, the scanner, storage and listening."""
        admin_only()
        now = time.time()
        with db() as conn:
            counts = conn.execute(
                "SELECT (SELECT COUNT(*) FROM albums) AS albums, "
                "(SELECT COUNT(*) FROM tracks) AS tracks, "
                "(SELECT COALESCE(SUM(duration), 0) FROM tracks) AS duration, "
                "(SELECT COALESCE(SUM(size), 0) FROM tracks) AS bytes"
            ).fetchone()
            counts = dict(counts) | {"artists": _artist_count(conn)}
            week = conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(t.duration), 0) AS secs, COUNT(DISTINCT p.user_id) AS people "
                "FROM plays p JOIN tracks t ON t.id = p.track_id WHERE p.played_at > ?", (now - 7 * 86400,),
            ).fetchone()
            days = conn.execute(
                "SELECT CAST((? - played_at) / 86400 AS INTEGER) AS d, COUNT(*) AS n FROM plays "
                "WHERE played_at > ? GROUP BY d", (now, now - 14 * 86400),
            ).fetchall()
            measured = conn.execute("SELECT COUNT(*) FROM tracks WHERE loud_checked = 1").fetchone()[0]
            rhythm = conn.execute(f"SELECT COUNT(*) FROM tracks WHERE rhythm_checked >= {analysis.VERSION}").fetchone()[0]
            sounded = conn.execute("SELECT COUNT(*) FROM tracks WHERE sound_checked = ?", (sound.version(),)).fetchone()[0]
            last_scan = get_meta(conn, "last_scan")
            users = _users_json(conn)
        per_day = [0] * 14
        for r in days:
            if 0 <= r["d"] < 14:
                per_day[13 - r["d"]] = r["n"]
        cover_bytes = sum(p.stat().st_size for p in cfg.cover_dir.glob("*.webp"))
        return {
            "library": dict(counts),
            "scan": scanner.state, "lastScan": float(last_scan) if last_scan else None,
            "loudnessMeasured": measured, "rhythmMeasured": rhythm, "soundMeasured": sounded,
            "week": {"plays": week["n"], "seconds": round(week["secs"]), "people": week["people"]},
            "playsPerDay": per_day,
            "storage": {"transcodeBytes": transcode.cache_size(cfg.transcode_dir), "coverBytes": cover_bytes,
                        "transcodeLimitBytes": cfg.transcode_cache_mb * 1024 * 1024},
            "users": users,
            "signins": auth.failures(),
            "devices": sum(len(h.devices) for h in hubs.values()),
            "version": __version__,
            "update": new_version.info(),
            "shares": _sharing_on(),
            "lastfm": lastfm.keys(cfg.db_path) is not None,
            "watch": {"path": str(_watch_dir()) if _watch_dir() else None},
            "backups": _backups_view(),
        }

    @app.post("/api/admin/update/check")
    def update_check():
        """Look for a newer Shelf now (it also looks every six hours)."""
        admin_only()
        return new_version.check()

    @app.patch("/api/admin/update/auto")
    def update_auto(body: AutoUpdateBody):
        """Install updates by themselves (at night, when nothing's playing), or only when asked."""
        admin_only()
        new_version.set_auto(body.enabled)
        return new_version.info()

    @app.post("/api/admin/update")
    def update_now():
        """Update this server to the latest release; it restarts itself."""
        admin_only()
        try:
            return {"message": new_version.update(updates.restart_in_place), **new_version.info()}
        except ValueError as e:
            raise HTTPException(409, str(e))

    # ---------- library ----------

    @app.get("/api/library")
    def library():
        with db() as conn:
            counts = conn.execute(
                "SELECT (SELECT COUNT(*) FROM albums) AS albums, "
                "(SELECT COUNT(*) FROM tracks) AS tracks, "
                "(SELECT COALESCE(SUM(duration), 0) FROM tracks) AS duration"
            ).fetchone()
            counts = dict(counts) | {"artists": _artist_count(conn)}
            last_scan = get_meta(conn, "last_scan")
            measured = conn.execute("SELECT COUNT(*) FROM tracks WHERE loud_checked = 1").fetchone()[0]
            rhythm = conn.execute(f"SELECT COUNT(*) FROM tracks WHERE rhythm_checked >= {analysis.VERSION}").fetchone()[0]
        return {
            **dict(counts),
            "lastScan": float(last_scan) if last_scan else None,
            "scan": scanner.state,
            "loudnessMeasured": measured,
            "rhythmMeasured": rhythm,
            "musicDirs": [str(d) for d in cfg.music_dirs],
        }

    # ---------- music folders ----------

    def _folders_state():
        return {"folders": folders.counts(cfg.db_path, cfg.music_dirs), "locked": folders.locked(),
                "scan": scanner.state}

    @app.get("/api/folders")
    def list_folders():
        return _folders_state()

    @app.get("/api/folders/browse")
    def browse_folders(path: str | None = Query(None, max_length=4096)):
        admin_only()
        return folders.browse(path, cfg.music_dirs)

    def _unlocked():
        if folders.locked():
            raise HTTPException(409, "Music folders are set by SHELF_MUSIC_DIRS on the server, so they can’t be changed here")

    @app.post("/api/folders")
    def add_folder(body: FolderBody):
        """Add a folder, or with `replace`, change one (songs found at the same place under
        the new folder keep their likes, playlists and history)."""
        admin_only()
        _unlocked()
        old = next((d for d in cfg.music_dirs if str(d) == body.replace), None) if body.replace else None
        if body.replace and old is None:
            raise HTTPException(404, "That folder isn’t in your library")
        try:
            new = folders.check_new(body.path, cfg.music_dirs, cfg.data_dir, replacing=old)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        moved = folders.remap(cfg.db_path, old, new) if old is not None else 0
        dirs = [new if d == old else d for d in cfg.music_dirs] if old is not None else [*cfg.music_dirs, new]
        cfg.music_dirs = dirs
        folders.save(cfg.db_path, dirs)
        scanner.trigger()
        return {**_folders_state(), "kept": moved}

    @app.delete("/api/folders")
    def remove_folder(path: str = Query(..., max_length=4096)):
        """Take a folder out of the library. Its songs leave the library (the files stay)."""
        admin_only()
        _unlocked()
        if path not in [str(d) for d in cfg.music_dirs]:
            raise HTTPException(404, "That folder isn’t in your library")
        cfg.music_dirs = [d for d in cfg.music_dirs if str(d) != path]
        folders.save(cfg.db_path, cfg.music_dirs)
        scanner.trigger()
        return _folders_state()

    # ---------- DJ ----------

    def _dj_settings(conn) -> dict:
        get = lambda k: get_meta(conn, f"dj_{k}")
        # No choice made yet: the built-in writer if it's downloaded, else Gemini.
        provider = get("provider") or ("builtin" if llm.installed() else "gemini")
        env_key = {"gemini": os.environ.get("GEMINI_API_KEY"), "anthropic": os.environ.get("ANTHROPIC_API_KEY")}.get(provider)
        return {"provider": provider, "key": get(f"key_{provider}") or env_key, "model": get("model") or None,
                "voice": get("voice") or dj.DEFAULT_VOICE, "speed": float(get("speed") or 1.0),
                "geminiKey": get("key_gemini") or os.environ.get("GEMINI_API_KEY"), "say": get("say") or "",
                "expressive": float(get("expressive") or 0.6), "cohost": get("cohost") or ""}

    def _dj_on() -> bool:
        """The DJ is on the shelf (experimental): off until an admin turns it on."""
        with db() as conn:
            return get_meta(conn, "dj_enabled") == "1"

    def _require_dj() -> None:
        if not _dj_on():
            raise HTTPException(404, "The DJ is turned off on this server")

    @app.get("/api/dj/settings")
    def dj_settings():
        admin_only()
        with db() as conn:
            s = _dj_settings(conn)
        return {"provider": s["provider"], "hasKey": bool(s["key"]), "model": s["model"] or "",
                "defaultModel": dj.DEFAULT_MODELS.get(s["provider"], ""), "voice": s["voice"], "speed": s["speed"],
                "providers": dj.PROVIDERS, "voices": dj.VOICES, "geminiVoices": dj.GEMINI_VOICES,
                "naturalVoices": dj.NATURAL_VOICES, "natural": natural.info(), "expressive": s["expressive"],
                "cohost": s["cohost"],
                "hasGeminiKey": bool(s["geminiKey"]), "say": s["say"], "builtinSay": dj.SAY,
                "voiceReady": dj_voice.available, "builtin": llm.info(), "enabled": _dj_on()}

    @app.post("/api/dj/natural")
    def install_natural():
        """Set up the natural voice (Chatterbox) in the background."""
        admin_only()
        natural.install()
        return dj_settings()

    @app.post("/api/dj/builtin/{model}")
    def install_builtin(model: str):
        """Download llama.cpp and a model for the built-in writer (in the background)."""
        admin_only()
        try:
            llm.install(model)
        except ValueError as e:
            raise HTTPException(409, str(e)) from e
        from .db import set_meta
        with db() as conn:
            set_meta(conn, "dj_provider", "builtin")
            set_meta(conn, "dj_model", model)
        return dj_settings()

    @app.delete("/api/dj/builtin/{model}")
    def remove_builtin(model: str):
        admin_only()
        llm.remove(model)
        return dj_settings()

    @app.patch("/api/dj/settings")
    def edit_dj_settings(body: DJSettings):
        admin_only()
        from .db import set_meta
        if body.enabled is not None:
            with db() as conn:
                set_meta(conn, "dj_enabled", "1" if body.enabled else "0")
            if not body.enabled:  # give the memory and graphics card back straight away
                llm.stop()
                natural.stop()
                dj_voice.stop()
                dj_prepared.clear()
                dj_sessions.clear()
        with db() as conn:
            provider = body.provider if body.provider in dj.PROVIDERS else (get_meta(conn, "dj_provider") or "gemini")
            set_meta(conn, "dj_provider", provider)
            if body.key is not None:
                set_meta(conn, f"dj_key_{provider}", body.key.strip())
            if body.model is not None:
                set_meta(conn, "dj_model", body.model.strip())
            if body.expressive is not None:
                set_meta(conn, "dj_expressive", str(body.expressive))
            if body.voice in dj.VOICES or body.voice in dj.GEMINI_VOICES or body.voice in dj.NATURAL_VOICES:
                set_meta(conn, "dj_voice", body.voice)
            if body.say is not None:
                set_meta(conn, "dj_say", body.say.strip())
            if body.cohost is not None and (body.cohost == "" or body.cohost in dj.VOICES or body.cohost in dj.NATURAL_VOICES
                                            or body.cohost in dj.GEMINI_VOICES):
                set_meta(conn, "dj_cohost", body.cohost)
            if body.speed is not None:
                set_meta(conn, "dj_speed", str(body.speed))
        return dj_settings()

    def _post_of(t: dict) -> float:
        """Seconds into a song where the singing (or the full band) comes in: the DJ's "post"."""
        m = t.get("mix") or {}
        intro = (m.get("intro") or 0) - (m.get("start") or 0)
        return float(min(max(intro, 0.0), 30.0)) if intro > 2 else 6.0

    def _play_facts(me_id: int, t: dict | None) -> str | None:
        """How this person has played a song, as a sentence for the DJ."""
        if not t:
            return None
        now = time.time()
        with db() as conn:
            r = conn.execute("SELECT COUNT(*) AS n, MAX(played_at) AS last, "
                             "SUM(played_at > ?) AS month FROM plays WHERE user_id = ? AND track_id = ?",
                             (now - 30 * 86400, me_id, t["id"])).fetchone()
        if not r["n"]:
            return f"They've never played {dj.speakable_title(t['title'])} before."
        if (r["month"] or 0) >= 3:
            return f"They've played it {r['month']} times this month."
        if r["last"] and now - r["last"] > 120 * 86400:
            return f"They haven't played it in about {round((now - r['last']) / (30 * 86400))} months."
        return None

    def _friend_fact(me_id: int, artist: str) -> str | None:
        """Someone else here who's been playing this artist (if they share their listening)."""
        now = time.time()
        with db() as conn:
            r = conn.execute(
                """SELECT u.username, COUNT(*) AS n FROM plays p JOIN users u ON u.id = p.user_id
                   JOIN tracks t ON t.id = p.track_id
                   WHERE p.user_id != ? AND u.share_activity = 1 AND p.played_at > ?
                     AND (t.artist = ? COLLATE NOCASE OR t.album_artist = ? COLLATE NOCASE)
                   GROUP BY u.id ORDER BY n DESC LIMIT 1""", (me_id, now - 7 * 86400, artist, artist)).fetchone()
        return f"{r['username'].split()[0]} has played {artist} {r['n']} times this week." if r and r["n"] >= 3 else None

    def _dj_line(kind: str, user: User, nxt: dict, prev: dict | None, seg: dict | None, when: str, hour: int) -> dict:
        """What the DJ says before `nxt` (over the end of `prev`, if there is one), spoken."""
        with db() as conn:
            s = _dj_settings(conn)
        name = user.username.split()[0]
        post = _post_of(nxt)
        # Room to talk: the next song's intro, plus a little over the end of the previous song
        # (more for a proper break than for a quick link).
        room = post + (0 if kind == "open" else 6 if kind == "break" else 2.5)
        about = None
        if kind != "link" and ((seg or {}).get("theme") == "spotlight" or random.random() < 0.4):
            _, data = artist_info.cached(cfg.db_path, videos.fold(nxt.get("albumArtist") or nxt["artist"]), "about")
            about = (data or {}).get("extract")
        friend = _friend_fact(user.id, nxt.get("albumArtist") or nxt["artist"]) if random.random() < 0.5 else None
        prompt = dj.prompt_for(kind, name, when, prev, nxt, seg, _play_facts(user.id, prev) if prev and kind != "open" else None,
                               _play_facts(user.id, nxt), about, friend, room)
        text = dj.write_line(s["provider"], s["key"], s["model"], prompt)
        wrote = text is not None
        text = text or dj.fallback_line(kind, name, hour, prev, nxt, seg)
        voice = None
        if dj_voice.available:
            try:
                clip, seconds = dj_voice.speak(dj.for_speech(text, dj.parse_say(s["say"])), s["voice"], s["speed"], s["geminiKey"])
                voice = {"url": f"api/dj/clip/{clip}", "seconds": seconds}
            except (OSError, subprocess.SubprocessError) as e:
                log.warning("The DJ's voice failed: %s", e)
        return {"kind": kind, "text": text, "voice": voice, "written": wrote, "post": post,
                "sting": kind in ("open", "break"), "next": nxt["id"]}

    notes_pending: set[str] = set()

    def _artist_notes(artist: str) -> list[str] | None:
        """Two or three things a host could say about an artist: written once by the language
        model from the cached Wikipedia summary, then kept. Until then, its first sentence."""
        key = videos.fold(artist)
        _, notes = artist_info.cached(cfg.db_path, key, "dj_notes")
        if notes:
            return notes
        _, about = artist_info.cached(cfg.db_path, key, "about")
        extract = (about or {}).get("extract")
        if not extract:
            return None
        if key not in notes_pending:
            notes_pending.add(key)
            notes_queue.append((artist, key, extract))
        first = dj.first_sentence(extract)
        return [first] if first else None

    notes_queue: list[tuple[str, str, str]] = []

    def _write_notes_later() -> None:
        """Artist notes, written after the set's own request so a set never waits behind them
        (they share one model on the built-in writer). One artist at a time, once each."""
        jobs = notes_queue[:]
        notes_queue.clear()
        if not jobs:
            return

        def work():
            for artist, key, extract in jobs:
                try:
                    with db() as conn:
                        s = _dj_settings(conn)
                    got = dj.parse_notes(dj.write(s["provider"], s["key"], s["model"], dj.NOTES_SYSTEM,
                                                  dj.notes_prompt(artist, extract), json_mode=True, max_tokens=200))
                    if got:
                        artist_info.store(cfg.db_path, key, "dj_notes", got)
                finally:
                    notes_pending.discard(key)
        threading.Thread(target=work, name="shelf-dj-notes", daemon=True).start()

    def _speak(text: str, s: dict) -> dict | None:
        if not dj_voice.available:
            return None
        dj_voice.expressiveness = s["expressive"]
        try:
            clip, seconds = dj_voice.speak(dj.for_speech(text, dj.parse_say(s["say"])), s["voice"], s["speed"], s["geminiKey"])
            return {"url": f"api/dj/clip/{clip}", "seconds": seconds}
        except (OSError, subprocess.SubprocessError) as e:
            log.warning("The DJ's voice failed: %s", e)
            return None

    def _dj_set(kind: str, user: User, seg: dict, prev: dict | None, day: str, hour: int, minute: int | None) -> list[dict]:
        """Everything the host says in a set, written in one request: the break before song 1
        and a quick link before every third song. Each line spoken, ready to play."""
        with db() as conn:
            s = _dj_settings(conn)
        tracks = seg["tracks"]
        name = user.username.split()[0]
        links = seg.get("links") or dj.link_positions(len(tracks))
        posts = [_post_of(t) for t in tracks]
        intro_words = dj.words_for(posts[0] + (0 if kind in ("open", "request") else 6))
        link_words = [min(25, dj.words_for(posts[i] + 2.5)) for i in links]
        facts = [(f"Number {t['rank']} in the countdown, played {t['plays']} times this week."
                  if t.get("rank") else _play_facts(user.id, t) if i == 0 or i in links else None)
                 for i, t in enumerate(tracks)]
        if seg.get("why") and not facts[0]:
            facts[0] = seg["why"]
        notes = {}
        for t in tracks[:1] + [tracks[i] for i in links]:
            a = t.get("albumArtist") or t["artist"]
            if a not in notes:
                got = _artist_notes(a)
                if got:
                    notes[a] = got
        sess = dj_sessions.setdefault(user.id, {"turn": 0, "artists": set()})
        recent = sess.setdefault("said", [])[-3:]
        friend = _friend_fact(user.id, tracks[0].get("albumArtist") or tracks[0]["artist"]) if random.random() < 0.5 else None
        liked = None
        if s["provider"] != "builtin":  # (a small model would copy them)
            with db() as conn:
                liked = [r[0] for r in conn.execute(
                    "SELECT text FROM dj_feedback WHERE user_id = ? AND kind = 'up' AND text IS NOT NULL ORDER BY at DESC LIMIT 3",
                    (user.id,))] or None
        # Two hosts at the opening and the breaks, when a co-host voice is chosen.
        duo = bool(s["cohost"]) and kind in ("open", "break") and s["provider"] != "none"
        # The time now and then (the opening and every third break), not at every break.
        sess["breaks"] = sess.get("breaks", 0) + 1
        give_time = minute is not None and (kind == "open" or sess["breaks"] % 3 == 1)
        prompt = dj.set_prompt(kind, name, day if give_time or kind == "open" else "", dj.time_words(hour, minute) if give_time else None, prev, tracks,
                               links, intro_words, link_words, facts, notes, seg, friend, recent, liked,
                               dialogue=duo)
        answer = dj.write(s["provider"], s["key"], s["model"], dj.SET_SYSTEM, prompt, json_mode=True,
                          max_tokens=160 + 60 * len(links) + (100 if duo else 0), schema=dj.set_schema(links, duo))
        turns = dj.parse_dialogue(answer) if duo else None
        if turns:  # two hosts: each turn checked; the last one names the song
            turns = [(who, line) for who, line in turns if dj.checked(line, prompt)]
            if len(turns) >= 2:
                turns[-1] = (turns[-1][0], dj.ensure_named(turns[-1][1], tracks[0]))
            else:
                turns = None
        intro, link_lines = dj.parse_set(answer, links) if not turns else (None, dj.parse_set(answer, links)[1])
        # Nothing said that the facts given don't back up.
        intro = dj.checked(intro, prompt)
        link_lines = {i: v for i, v in link_lines.items() if dj.checked(v, prompt)}
        talks = []
        if turns:
            voice = None
            if dj_voice.available:
                try:
                    dj_voice.expressiveness = s["expressive"]
                    say = dj.parse_say(s["say"])
                    clip, seconds = dj_voice.dialogue([(w, dj.for_speech(l, say)) for w, l in turns], s["voice"], s["cohost"],
                                                      s["speed"], s["geminiKey"])
                    voice = {"url": f"api/dj/clip/{clip}", "seconds": seconds}
                except (OSError, subprocess.SubprocessError) as e:
                    log.warning("The DJ's two voices failed: %s", e)
            talks.append({"kind": kind, "theme": seg["theme"], "text": "\n".join(l for _, l in turns), "written": True,
                          "next": tracks[0]["id"], "post": posts[0], "sting": True, "voice": voice, "duo": True})
        else:
            line = dj.ensure_named(dj.fit(intro, intro_words), tracks[0]) if intro else dj.fallback_line(kind, name, hour, prev, tracks[0], seg)
            talks.append({"kind": kind, "theme": seg["theme"], "text": line, "written": intro is not None, "next": tracks[0]["id"],
                          "post": posts[0], "sting": True, "voice": _speak(line, s)})
        for i in links:
            text = dj.ensure_named(dj.fit(link_lines[i], link_words[links.index(i)]), tracks[i]) if i in link_lines \
                else dj.fallback_line("link", name, hour, tracks[i - 1], tracks[i], None)
            talks.append({"kind": "link", "text": text, "written": i in link_lines, "next": tracks[i]["id"],
                          "post": posts[i], "sting": False, "voice": _speak(text, s)})
        sess["said"] = (sess["said"] + [t["text"] for t in talks])[-4:]
        _write_notes_later()
        return talks

    def _set_json(seg: dict, talks: list[dict]) -> dict:
        # The first talk's fields at the top level too, for apps that only know about one.
        return {"theme": seg["theme"], "tracks": seg["tracks"], "talks": talks, **talks[0]}

    THEMES = ["favourites", "discover", "throwback", "spotlight", "deep"]  # (and "countdown", once a show)
    BRIEFS = {
        "favourites": "Songs they've had on repeat lately, plus a couple that fit with them.",
        "discover": "Songs from their own collection they have never played, picked because they sound like their favourites.",
        "throwback": "Songs they used to play a lot but haven't in months.",
        "spotlight": "A few songs in a row by one artist they love.",
        "deep": "Deeper cuts: songs they've rarely played from albums they love.",
        "countdown": "The weekly countdown: their most played songs of the past week, from the bottom up. Give each one its number.",
    }

    def _target_energy(hour: int) -> float:
        """How lively the music should be at this hour: bright days, a mellower late night."""
        return 0.62 if 5 <= hour < 12 else 0.66 if 12 <= hour < 18 else 0.58 if 18 <= hour < 22 else 0.35

    def _shape(tracks: list[dict], energy: dict[int, float], hour: int) -> list[dict]:
        """Order a set like a DJ would: building up (or, late at night, winding down) in energy,
        with no big jumps in tempo from one song to the next."""
        if len(tracks) < 3:
            return tracks
        down = hour >= 22 or hour < 5
        first = sorted(tracks, key=lambda t: energy.get(t["id"], 0.5), reverse=down)[0]
        out, rest = [first], [t for t in tracks if t is not first]
        while rest:
            prev = out[-1]
            want = energy.get(prev["id"], 0.5) + (-0.08 if down else 0.08)
            def cost(t):
                jump = abs((t.get("bpm") or 0) - (prev.get("bpm") or 0)) / 40 if t.get("bpm") and prev.get("bpm") else 0.3
                return abs(energy.get(t["id"], 0.5) - want) + 0.5 * min(jump, 1)
            nxt = min(rest, key=cost)
            out.append(nxt)
            rest.remove(nxt)
        return out

    def _dj_tastes(me_id: int) -> tuple[set[int], dict[str, float], dict[str, int]]:
        """From the last month of DJ feedback: songs skipped (left out for now), how much each
        theme is wanted (skips and switches count against it), and artists skipped a lot."""
        now = time.time()
        with db() as conn:
            rows = conn.execute(
                """SELECT f.kind, f.theme, f.track_id, t.artist, t.album_artist FROM dj_feedback f
                   LEFT JOIN tracks t ON t.id = f.track_id WHERE f.user_id = ? AND f.at > ?""",
                (me_id, now - 30 * 86400)).fetchall()
        skipped = {r["track_id"] for r in rows if r["kind"] == "skip" and r["track_id"]}
        themes: dict[str, float] = {}
        artists: dict[str, int] = {}
        for r in rows:
            if r["kind"] in ("skip", "switch") and r["theme"]:
                themes[r["theme"]] = themes.get(r["theme"], 0) - (2 if r["kind"] == "switch" else 1)
            if r["kind"] == "skip" and (r["album_artist"] or r["artist"]):
                a = r["album_artist"] or r["artist"]
                artists[a] = artists.get(a, 0) + 1
        weights = {t: max(0.2, 1 + 0.15 * themes.get(t, 0)) for t in THEMES}
        return skipped, weights, artists

    def _dj_segment(me_id: int, exclude: set[int], hour: int = 12, want: dict | None = None) -> dict | None:
        """The next few songs, themed and shaped, for this person's DJ session. `want`: a
        request ({"theme", "artist", "energy"})."""
        want = want or {}
        now = time.time()
        with db() as conn:
            rows = conn.execute(TRACK_SELECT).fetchall()
            plays = [(r[0], r[1]) for r in conn.execute(
                "SELECT track_id, played_at FROM plays WHERE user_id = ? AND played_at > ?", (me_id, now - 400 * 86400))]
            liked = {r[0] for r in conn.execute("SELECT track_id FROM likes WHERE user_id = ?", (me_id,))}
        sess = dj_sessions.setdefault(me_id, {"turn": 0, "artists": set()})
        skipped, theme_weights, skipped_artists = _dj_tastes(me_id)
        energy = sound.energy(rows)
        target = want.get("energy") if want.get("energy") is not None else _target_energy(hour)
        score = mixes.affinity(plays, liked, now)
        by_id = {r["id"]: r for r in rows}
        recent = {}
        for tid, at in plays:
            if at > now - 30 * 86400:
                recent[tid] = recent.get(tid, 0) + 1
        # Skipped songs sit out a month; artists skipped again and again come up less.
        pool = [r for r in rows if r["id"] not in exclude and r["id"] not in skipped
                and skipped_artists.get(mixes.artist_of(r), 0) < 4]
        pool_ids = {r["id"] for r in pool}
        rng = random.Random()
        favs = sorted((r for r in rows if score.get(r["id"]) and r["id"] in pool_ids), key=lambda r: -score[r["id"]])
        fit = lambda tid: abs(energy.get(tid, target) - target)  # how far a song is from the energy wanted

        def best(cands: list, n: int) -> list:
            """n of the candidates, favouring the energy wanted (with some variety)."""
            return sorted(cands, key=lambda r: fit(r["id"]) + rng.random() * 0.25)[:n]

        def pick(theme):
            if theme == "favourites" and favs:
                chosen = best(favs[:16], 2)
                if not chosen:
                    return None
                more = _recommend(chosen, [r for r in pool if r["id"] not in {c["id"] for c in chosen}], rng.randrange(1, 10**6), 8)
                more = sorted(more, key=lambda t: fit(t["id"]) + rng.random() * 0.25)[:3]
                first = chosen[0]
                n = recent.get(first["id"], 0)
                why = f"They've played {first['title']} {n} times in the last month." if n > 1 else "It's one of their favourites."
                return [track_json(c) for c in chosen] + more, why
            if theme == "discover":
                got = [t for t in mixes.discover(rows, plays, score, _recommend, f"{rng.random()}") if t["id"] in pool_ids]
                got = sorted(got, key=lambda t: fit(t["id"]) + rng.random() * 0.25)[:5]
                if len(got) < 3:
                    unplayed = [r for r in pool if r["id"] not in {p for p, _ in plays}]
                    got = [track_json(r) for r in best(unplayed, 5)]
                return (got, "They have never played it.") if got else None
            if theme == "throwback":
                got = [r for r in mixes.rediscover(by_id, plays, now) if r["id"] in pool_ids]
                got = best(got, 5)
                if len(got) < 2:
                    return None
                last = max(at for tid, at in plays if tid == got[0]["id"])
                months = max(2, round((now - last) / (30 * 86400)))
                return [track_json(r) for r in got], f"They used to play it a lot; the last time was about {months} months ago."
            if theme == "spotlight":
                if want.get("artist"):
                    artist = want["artist"]
                else:
                    weights = {}
                    for r in favs[:60]:
                        a = mixes.artist_of(r)
                        weights[a] = weights.get(a, 0) + score[r["id"]]
                    names = [a for a in sorted(weights, key=lambda a: -weights[a]) if a not in sess["artists"]] or \
                            [a for a in {mixes.artist_of(r) for r in pool} if a not in sess["artists"]]
                    if not names:
                        return None
                    artist = names[0] if weights else rng.choice(names)
                sess["artists"].add(artist)
                theirs = [r for r in pool if videos.fold(mixes.artist_of(r)) == videos.fold(artist)
                          or videos.fold(artist) in videos.fold(r["artist"])]
                theirs.sort(key=lambda r: -(score.get(r["id"], 0) + rng.random() - fit(r["id"])))
                got = theirs[:4]
                if len(got) < 2:
                    return None
                n = sum(recent.get(r["id"], 0) for r in theirs)
                return [track_json(r) for r in got], (f"They've played {artist} {n} times this month." if n else None)
            if theme == "deep":
                fav_albums = {r["album_id"] for r in favs[:40]}
                got = [r for r in pool if r["album_id"] in fav_albums and score.get(r["id"], 0) < 0.5]
                got = best(got, 4)
                return ([track_json(r) for r in got], "A song they've rarely played, from an album they love.") if len(got) >= 2 else None
            if theme == "countdown":
                week = {}
                for tid, at in plays:
                    if at > now - 7 * 86400 and tid in by_id:
                        week[tid] = week.get(tid, 0) + 1
                top = [tid for tid, n in sorted(week.items(), key=lambda x: -x[1]) if n >= 2][:5]
                if len(top) < 4:
                    return None
                tracks = []
                for rank, tid in reversed(list(enumerate(top, 1))):
                    t = track_json(by_id[tid])
                    t["rank"], t["plays"] = rank, week[tid]
                    tracks.append(t)
                return tracks, f"Their top {len(top)} songs of the past week, counted down from number {len(top)}."
            return None

        # The theme: a request first; otherwise the ones they skip less, not the same twice in a
        # row, and the weekly countdown once a show (after a couple of sets).
        order = []
        if want.get("theme"):
            order.append(want["theme"])
        if not want and not sess.get("countdown") and sess["turn"] >= 2 and rng.random() < 0.5:
            order.append("countdown")
        pool_themes = [t for t in THEMES if t != sess.get("last")]
        while pool_themes:
            t = rng.choices(pool_themes, weights=[theme_weights.get(x, 1) for x in pool_themes])[0]
            order.append(t)
            pool_themes.remove(t)
        for theme in order:
            if not favs and theme in ("favourites", "throwback", "deep", "countdown"):
                continue  # someone new: there's nothing to go on yet
            got = pick(theme)
            if not got or not got[0]:
                continue
            sess["turn"] += 1
            sess["last"] = theme
            if theme == "countdown":
                sess["countdown"] = True
            tracks, why = got
            # One version of a song per segment ("Beggin'" and "Beggin' - Live" are the same song).
            seen_songs, unique = set(), []
            for t in tracks:
                k = (videos.fold(dj.speakable_title(t["title"])), videos.fold(t["artist"]))
                if k not in seen_songs:
                    seen_songs.add(k)
                    unique.append(t)
            tracks = unique if theme == "countdown" else _shape(unique, energy, hour)
            links = list(range(1, len(tracks))) if theme == "countdown" else dj.link_positions(len(tracks))
            for i, t in enumerate(tracks):
                r = by_id.get(t["id"])
                t["year"] = r["year"] if r else None  # for the DJ to mention
                t["energy"] = energy.get(t["id"])
                # Blend into the next song inside a set; a clean ending where the host talks next.
                t["transition"] = "cut" if i == len(tracks) - 1 or (i + 1) in links else "auto"
            brief = BRIEFS[theme] if not want.get("text") else f"A request from the listener: \"{want['text']}\"."
            return {"theme": theme, "brief": brief, "why": why, "tracks": tracks, "links": links}
        return None

    def _dj_opening(user: User, day: str, hour: int, minute: int | None) -> dict | None:
        dj_sessions.pop(user.id, None)
        seg = _dj_segment(user.id, set(), hour)
        if not seg:
            return None
        return _set_json(seg, _dj_set("open", user, seg, None, day, hour, minute))

    @app.post("/api/dj/prepare")
    def dj_prepare(body: DJNext):
        """Make the DJ's opening ahead (from Home), so pressing DJ starts it straight away,
        even where writing a line takes a while. Told only the day and part of day, since it
        may be heard a little later."""
        _require_dj()
        user = me()
        have = dj_prepared.get(user.id)
        if have and (have.get("busy") or time.time() - have["at"] < 15 * 60):
            return {"ok": True}
        dj_prepared[user.id] = {"at": time.time(), "busy": True}

        def work():
            try:
                result = _dj_opening(user, body.when, body.hour, None)  # made ahead: no clock time
                dj_prepared[user.id] = {"at": time.time(), "result": result, "session": dj_sessions.get(user.id)}
            except Exception:
                log.exception("Preparing the DJ's opening failed")
                dj_prepared.pop(user.id, None)
        threading.Thread(target=work, name="shelf-dj-prepare", daemon=True).start()
        return {"ok": True}

    @app.post("/api/dj/next")
    def dj_next(body: DJNext):
        """The DJ's next segment: a few songs and what the DJ says before them."""
        _require_dj()
        user = me()
        if body.first:
            have = dj_prepared.pop(user.id, None)
            if have and have.get("result") and time.time() - have["at"] < 30 * 60:
                dj_sessions[user.id] = have["session"] or {"turn": 1, "artists": set()}
                return have["result"]
            dj_sessions.pop(user.id, None)
        # Played everything already (a small shelf, or a long session)? Then repeats are fine.
        seg = _dj_segment(user.id, set(body.exclude), body.hour) or _dj_segment(user.id, set(), body.hour)
        if not seg:
            raise HTTPException(404, "There isn’t enough music on the shelf for the DJ yet")
        prev = None
        if body.previous is not None and not body.first:
            with db() as conn:
                r = conn.execute(f"{TRACK_SELECT} WHERE t.id = ?", (body.previous,)).fetchone()
            prev = track_json(r) if r else None
        return _set_json(seg, _dj_set("open" if body.first else "break", user, seg, prev, body.when, body.hour, body.minute))

    @app.post("/api/dj/feedback")
    def dj_feedback(body: DJFeedback):
        """A skip, a "switch it up", or a thumb up or down on something the host said. Skips and
        switches steer future sets; thumbs are kept (the liked lines guide the host's style)."""
        _require_dj()
        with db() as conn:
            conn.execute("INSERT INTO dj_feedback(user_id, track_id, theme, kind, text, at) VALUES(?, ?, ?, ?, ?, ?)",
                         (uid(), body.track, body.theme, body.kind, body.text, time.time()))
        return {"ok": True}

    MOODS = {
        0.15: ("chill", "calm", "mellow", "relax", "quiet", "soft", "slow", "sleep", "study", "focus", "acoustic", "sad", "rainy"),
        0.88: ("party", "hype", "energy", "energetic", "upbeat", "loud", "heavy", "rock out", "workout", "gym", "pump",
               "fast", "dance", "banger", "intense", "angry"),
    }

    def _understand(text: str, rows) -> dict:
        """What a request asks for: an artist on the shelf, a theme, or a mood (energy). Read
        from the words first; the language model only helps when the words don't say."""
        t = videos.fold(text)
        want: dict = {"text": text.strip()}
        artists = sorted({mixes.artist_of(r) for r in rows} | {r["artist"] for r in rows}, key=len, reverse=True)
        for a in artists:
            fa = videos.fold(a)
            if len(fa) >= 3 and re.search(rf"(?<![a-z0-9]){re.escape(fa)}(?![a-z0-9])", t):
                want.update(theme="spotlight", artist=a)
                break
        for energy, words in MOODS.items():
            if any(re.search(rf"\b{re.escape(w)}\b", t) for w in words):
                want["energy"] = energy
        if "theme" not in want:
            if re.search(r"\b(new|never|haven't heard|havent heard|surprise|discover|different)\b", t):
                want["theme"] = "discover"
            elif re.search(r"\b(old|throwback|used to|nostalgi|back in the day|classic)\b", t):
                want["theme"] = "throwback"
            elif re.search(r"\b(favou?rite|best|my top|on repeat|loved)\b", t):
                want["theme"] = "favourites"
            elif re.search(r"\b(deep|rare|b.?sides?|album tracks)\b", t):
                want["theme"] = "deep"
        if "theme" not in want and "energy" not in want:
            # The words didn't say: ask the language model to pick an artist, theme or mood.
            with db() as conn:
                s = _dj_settings(conn)
            names = sorted({mixes.artist_of(r) for r in rows})[:200]
            got = dj._json(dj.write(s["provider"], s["key"], s["model"],
                                    "You map a music request to a choice. Answer JSON only.",
                                    f'Request: "{text}". Artists on the shelf: {", ".join(names)}. '
                                    'Answer {"artist": one of those artists or null, "mood": "calm", "lively" or null, '
                                    '"theme": "favourites", "discover", "throwback" or null}.',
                                    json_mode=True, max_tokens=80))
            if isinstance(got, dict):
                if got.get("artist") in names:
                    want.update(theme="spotlight", artist=got["artist"])
                if got.get("mood") in ("calm", "lively"):
                    want["energy"] = 0.15 if got["mood"] == "calm" else 0.85
                if got.get("theme") in THEMES and "theme" not in want:
                    want["theme"] = got["theme"]
        return want

    @app.post("/api/dj/request")
    def dj_request(body: DJRequest):
        """A request ("something chill", "more Slipknot"): the next set follows it, and the host
        says so."""
        _require_dj()
        user = me()
        with db() as conn:
            rows = conn.execute(TRACK_SELECT).fetchall()
        want = _understand(body.text, rows)
        seg = _dj_segment(user.id, set(body.exclude), body.hour, want) or _dj_segment(user.id, set(), body.hour, want)
        if not seg:
            raise HTTPException(404, "Couldn’t find music for that request")
        prev = None
        if body.previous is not None:
            with db() as conn:
                r = conn.execute(f"{TRACK_SELECT} WHERE t.id = ?", (body.previous,)).fetchone()
            prev = track_json(r) if r else None
        result = _set_json(seg, _dj_set("request", user, seg, prev, body.when, body.hour, body.minute))
        return {**result, "understood": {k: v for k, v in want.items() if k != "text"}}

    @app.post("/api/dj/link")
    def dj_link(body: DJLink):
        """A quick word between two songs: back-announce one, set up the other."""
        _require_dj()
        user = me()
        with db() as conn:
            rows = {r["id"]: r for r in conn.execute(f"{TRACK_SELECT} WHERE t.id IN (?, ?)", (body.previous, body.next))}
        if body.next not in rows:
            raise HTTPException(404, "Track not found")
        prev = track_json(rows[body.previous]) if body.previous in rows else None
        nxt = track_json(rows[body.next])
        nxt["year"] = rows[body.next]["year"]
        return _dj_line("link", user, nxt, prev, None, body.when, body.hour)

    @app.post("/api/dj/sample")
    def dj_sample():
        """A sample line in the chosen voice, for the admin dashboard."""
        _require_dj()
        user = admin_only()
        with db() as conn:
            s = _dj_settings(conn)
        if not dj_voice.available:
            raise HTTPException(409, "The DJ's voice isn’t installed on this server")
        name = user.username.split()[0]
        text = dj.write_line(s["provider"], s["key"], s["model"],
                             f"Listener's name: {name}. Say a short hello as their new DJ on Shelf and say you'll be "
                             "playing their own music between your chats. No song to name this time.") \
            or f"Hey {name}, I'm your DJ on Shelf. I'll play your music and drop in between songs now and then."
        text = dj.fit(text, 28)
        dj_voice.expressiveness = s["expressive"]
        clip, seconds = dj_voice.speak(dj.for_speech(text, dj.parse_say(s["say"])), s["voice"], s["speed"], s["geminiKey"])
        return {"text": text, "voice": {"url": f"api/dj/clip/{clip}", "seconds": seconds}}

    @app.get("/api/dj/clip/{clip}")
    def dj_clip(clip: str):
        path = dj_voice.path(clip)
        if not path:
            raise HTTPException(404, "No such clip")
        return FileResponse(path, media_type="audio/mp4", headers={"Cache-Control": "private, max-age=86400"})

    # ---------- CD ripping ----------

    @app.get("/api/cd")
    def cd_state():
        admin_only()
        return {"available": cd.available, "device": ripper.DEVICE, **cd.state}

    @app.post("/api/cd/read")
    def cd_read():
        admin_only()
        if not cd.available:
            raise HTTPException(409, "This server has no CD drive (or cd-paranoia isn’t installed)")
        cd.read_disc()
        return {"ok": True}

    @app.get("/api/cd/cover")
    def cd_cover():
        admin_only()
        data = cd.cover()
        if not data:
            raise HTTPException(404, "No cover")
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.post("/api/cd/rip")
    def cd_rip(body: RipBody):
        admin_only()
        roots = {str(d): d for d in cfg.music_dirs}
        root = roots.get(body.folder) if body.folder else (cfg.music_dirs[0] if cfg.music_dirs else None)
        if root is None:
            raise HTTPException(400, "Add a music folder first")
        if not body.artist.strip() or not body.album.strip():
            raise HTTPException(400, "Fill in the artist and album")
        try:
            cd.rip(root, body.artist.strip(), body.album.strip(), (body.year or "").strip() or None, body.titles, body.disc)
        except ValueError as e:
            raise HTTPException(409, str(e)) from e
        return {"ok": True}

    @app.post("/api/cd/cancel")
    def cd_cancel():
        admin_only()
        cd.cancel()
        return {"ok": True}

    @app.post("/api/cd/eject")
    def cd_eject():
        admin_only()
        cd.eject()
        return {"ok": True}

    # ---------- new releases ----------

    @app.get("/api/releases")
    def list_releases():
        """Albums and EPs by your artists that aren't on the shelf (from MusicBrainz)."""
        if not cfg.artist_info:
            return {"releases": [], "checkedAt": None, "state": {"running": False}, "off": True}
        return new_releases.get()

    @app.post("/api/releases/check")
    def check_releases():
        admin_only()
        new_releases.check_now()
        return {"ok": True}

    @app.get("/api/releases/{mbid}/cover")
    async def release_cover(mbid: str):
        data = await asyncio.to_thread(releases.cover, cfg.data_dir / "release-covers", mbid)
        if data is None:
            raise HTTPException(404, "No cover")
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=604800"})

    @app.post("/api/upload")
    async def upload(request: Request, name: str = Query(..., min_length=1, max_length=400),
                     folder: str | None = Query(None, max_length=4096), group: str = Query("upload", max_length=400)):
        """One song, cover image or ZIP, sent as the request body. Filed into a music folder
        by its tags (see uploads.py). Start a rescan afterwards to add it to the library."""
        admin_only()
        if not uploads.allowed(name):
            raise HTTPException(400, "Shelf takes songs (FLAC, MP3, AAC, Ogg and the like), cover pictures and ZIP files")
        roots = {str(d): d for d in cfg.music_dirs}
        root = roots.get(folder) if folder else (cfg.music_dirs[0] if cfg.music_dirs else None)
        if root is None:
            raise HTTPException(400, "Add a music folder first")
        staging = cfg.data_dir / "uploads"
        staging.mkdir(exist_ok=True)
        staged = staging / f"{time.time_ns()}{Path(name).suffix.lower()}"
        size = 0
        try:
            with open(staged, "wb") as out:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > uploads.MAX_BYTES:
                        raise HTTPException(413, "That file is too big (4 GB at most)")
                    out.write(chunk)
            return await asyncio.to_thread(uploads.place, staged, Path(name).name, root, group)
        except HTTPException:
            raise
        except (OSError, ValueError) as e:
            raise HTTPException(400, f"Couldn’t add {name}: {e}") from e
        finally:
            staged.unlink(missing_ok=True)

    @app.post("/api/scan")
    def rescan():
        admin_only()
        scanner.trigger()
        return {"ok": True}

    @app.get("/api/albums")
    def albums(sort: str = "artist", artist: str | None = None):
        order = ALBUM_SORTS.get(sort, ALBUM_SORTS["artist"])
        sql = (
            "SELECT albums.*, p.last_played FROM albums LEFT JOIN"
            " (SELECT album_key, MAX(played_at) AS last_played FROM plays WHERE user_id = ? GROUP BY album_key) p"
            " ON p.album_key = albums.key"
        )
        params = [uid()]
        if artist:
            order = "COALESCE(year, 9999), title COLLATE NOCASE"
        with db() as conn:
            rows = conn.execute(f"{sql} ORDER BY {order}", params).fetchall()
        if artist:  # their albums, shared ones too ("Aerosmith & Yungblud" is on both)
            rows = [r for r in rows if credits.credited(r["artist"], artist)]
        return [album_json(r) for r in rows]

    @app.get("/api/albums/{album_id}")
    def album(album_id: int):
        with db() as conn:
            row = conn.execute("SELECT * FROM albums WHERE id = ?", (album_id,)).fetchone()
            if not row:
                raise HTTPException(404, "Album not found")
            tracks = conn.execute(f"{TRACK_SELECT} WHERE a.id = ? {TRACK_ORDER}", (album_id,)).fetchall()
        lufs, peak = album_loudness(tracks)
        return {**album_json(row), "albumLufs": lufs, "albumPeak": peak, "tracks": [track_json(t) for t in tracks]}

    @app.get("/api/albums/{album_id}/cover")
    def album_cover(album_id: int, size: int = Query(320, ge=32, le=2000)):
        if podcasts.is_show(album_id):
            return _show_cover(album_id - podcasts.SHOW_BASE, size)
        with db() as conn:
            row = conn.execute("SELECT cover_src FROM albums WHERE id = ?", (album_id,)).fetchone()
        if not row or not row["cover_src"]:
            raise HTTPException(404, "No cover")
        path = covers.get_cover(cfg.cover_dir, row["cover_src"], size)
        if not path:
            raise HTTPException(404, "No cover")
        # URLs carry ?v=<cover hash>, so a changed cover gets a new URL.
        return FileResponse(path, media_type="image/webp",
                            headers={"Cache-Control": "private, max-age=31536000, immutable"})

    def _album_artists(rows) -> list[dict]:
        """Albums grouped by artist, a shared album counting for each of its artists:
        name, albums, tracks and the cover of their biggest album."""
        by: dict[str, dict] = {}
        for r in rows:
            for name in credits.names(r["artist"]):
                a = by.setdefault(videos.fold(name), {"name": name, "albums": 0, "tracks": 0, "cover": None})
                a["albums"] += 1
                a["tracks"] += r["track_count"]
                rank = (r["track_count"], r["year"] or 0)
                if r["cover_src"] and (a["cover"] is None or rank > a["cover"][0]):
                    a["cover"] = (rank, r["id"], r["cover_src"])
        return list(by.values())

    @app.get("/api/artists")
    def artists():
        with db() as conn:
            rows = conn.execute("SELECT id, artist, year, track_count, cover_src FROM albums").fetchall()
            mine = follows.followed(conn, uid())
        return [
            {"name": a["name"], "albums": a["albums"], "tracks": a["tracks"],
             "coverAlbumId": a["cover"][1] if a["cover"] else None,
             "cover": _cover_version(a["cover"][2]) if a["cover"] else None,
             "following": videos.fold(a["name"]) in mine}
            for a in sorted(_album_artists(rows), key=lambda a: a["name"].casefold())
        ]

    @app.put("/api/artist/follow")
    def follow_artist(name: str = Query(..., min_length=1, max_length=200)):
        """Follow an artist: they (and their albums) show in your Library."""
        with db() as conn:
            follows.follow(conn, uid(), credits.display(name))
        return {"following": True}

    @app.delete("/api/artist/follow")
    def unfollow_artist(name: str = Query(..., min_length=1, max_length=200)):
        with db() as conn:
            follows.unfollow(conn, uid(), credits.display(name))
        return {"following": False}

    @app.get("/api/search")
    def search(q: str = Query("", max_length=200)):
        terms = [t for t in q.split() if t][:6]
        if not terms:
            return {"artists": [], "albums": [], "tracks": []}

        def where(cols):
            clauses, params = [], []
            for t in terms:
                like = f"%{t.replace('%', r'\%').replace('_', r'\_')}%"
                clauses.append("(" + " OR ".join(f"{c} LIKE ? ESCAPE '\\'" for c in cols) + ")")
                params.extend([like] * len(cols))
            return " AND ".join(clauses), params

        with db() as conn:
            aw, ap = where(["artist"])
            matched = conn.execute(f"SELECT id, artist, year, track_count, cover_src FROM albums WHERE {aw}", ap).fetchall()
            folded = [videos.fold(t) for t in terms]
            artist_rows = sorted((a for a in _album_artists(matched) if all(f in videos.fold(a["name"]) for f in folded)),
                                 key=lambda a: -a["albums"])[:8]
            bw, bp = where(["title", "artist"])
            album_rows = conn.execute(
                f"SELECT * FROM albums WHERE {bw} ORDER BY artist COLLATE NOCASE, year LIMIT 24", bp,
            ).fetchall()
            tw, tp = where(["t.title", "t.artist", "a.title"])
            track_rows = conn.execute(
                f"{TRACK_SELECT} WHERE {tw} ORDER BY t.title COLLATE NOCASE LIMIT 50", tp,
            ).fetchall()
            # The podcasts you follow, and their episodes, are searched along with the music.
            me_id = uid()
            shows = [sh for sh in _my_shows(conn, me_id)
                     if all(f in videos.fold(f"{sh['title']} {sh['author']}") for f in folded)][:8]
            ew, ep = where(["e.title"])
            episodes = _episode_rows(conn, me_id, f"e.podcast_id IN (SELECT podcast_id FROM podcast_subs WHERE user_id = ?) AND {ew}",
                                     (me_id, *ep), 12)
        return {
            "artists": [{"name": a["name"], "albums": a["albums"]} for a in artist_rows],
            "albums": [album_json(r) for r in album_rows],
            "tracks": [track_json(r) for r in track_rows],
            "podcasts": shows,
            "episodes": episodes,
        }

    @app.get("/api/home")
    def home():
        now = time.time()
        me_id = uid()
        with db() as conn:
            recent = conn.execute(
                """
                SELECT a.*, MAX(p.played_at) AS last_played FROM albums a
                JOIN plays p ON p.album_key = a.key WHERE p.user_id = ?
                GROUP BY a.id ORDER BY last_played DESC LIMIT 14
                """, (me_id,)
            ).fetchall()
            top = conn.execute(
                """
                SELECT a.*, COUNT(p.id) AS plays FROM albums a
                JOIN plays p ON p.album_key = a.key WHERE p.user_id = ?
                GROUP BY a.id HAVING plays >= 3 ORDER BY plays DESC, MAX(p.played_at) DESC LIMIT 14
                """, (me_id,)
            ).fetchall()
            added = conn.execute("SELECT * FROM albums ORDER BY added_at DESC, artist, year LIMIT 14").fetchall()
            # Albums you haven't played in a month (or ever), in a new order each visit.
            rediscover = conn.execute(
                """
                SELECT * FROM albums a WHERE a.key NOT IN (
                    SELECT p.album_key FROM plays p WHERE p.played_at > ? AND p.user_id = ?
                ) ORDER BY RANDOM() LIMIT 14
                """,
                (now - 30 * 86400, me_id),
            ).fetchall()
            listened = conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(t.duration), 0) AS secs FROM plays p "
                "JOIN tracks t ON t.id = p.track_id WHERE p.played_at > ? AND p.user_id = ?",
                (now - 7 * 86400, me_id),
            ).fetchone()
            rows = _taste_rows(conn, me_id, now)
        out = {
            "recent": [album_json(r) | {"lastPlayed": r["last_played"]} for r in recent],
            "top": [album_json(r) | {"plays": r["plays"]} for r in top],
            "added": [album_json(r) for r in added],
            "rediscover": [album_json(r) for r in rediscover],
            "week": {"plays": listened["n"], "seconds": round(listened["secs"])},
        }
        # The rows to show, in the order this person's taste and use put them. "mixes" (Made
        # for you) and "releases" (New from your artists) are filled in by the apps.
        album_rows = {
            "following": ("From artists you follow", rows["following"]),
            "recent": ("Recently played", out["recent"]),
            "added": ("Recently added", out["added"]),
            "top": ("Most played", out["top"]),
            "rediscover": ("Haven’t heard these in a while", out["rediscover"] if len(out["rediscover"]) >= 4 else []),
            **{f"like:{name}": (f"More like {name}", albums) for name, albums in rows["like"]},
        }
        keys = ["mixes", "releases"] + [k for k, (_, albums) in album_rows.items() if albums]
        # Podcasts you follow: the episodes you're partway through, then new ones.
        with db() as conn:
            mine = "e.podcast_id IN (SELECT podcast_id FROM podcast_subs WHERE user_id = ?)"
            episodes = (_episode_rows(conn, me_id, f"{mine} AND st.position > 0 AND COALESCE(st.finished, 0) = 0", (me_id,), 8)
                        + _episode_rows(conn, me_id, f"{mine} AND COALESCE(st.finished, 0) = 0 AND COALESCE(st.position, 0) = 0 "
                                                     "AND e.published_at > ?", (me_id, now - 14 * 86400), 12))[:14]
            if len(episodes) < 6:
                # Quiet fortnight: the newest episode you haven't heard from each show you follow.
                have = {e["id"] for e in episodes}
                latest = _episode_rows(conn, me_id, f"""{mine} AND COALESCE(st.finished, 0) = 0 AND e.published_at = (
                    SELECT MAX(x.published_at) FROM episodes x LEFT JOIN episode_state xs ON xs.episode_id = x.id AND xs.user_id = ?
                    WHERE x.podcast_id = e.podcast_id AND COALESCE(xs.finished, 0) = 0)""", (me_id, me_id), 12)
                episodes += [e for e in latest if e["id"] not in have][:14 - len(episodes)]
        if episodes:
            keys.append("podcasts")
        out["rows"] = [
            {"key": k, "kind": home_rows.kind(k)} | (
                {"title": album_rows[k][0], "albums": album_rows[k][1]} if k in album_rows else {})
            | ({"title": "Your podcasts", "episodes": episodes} if k == "podcasts" else {})
            | ({"artist": k.split(":", 1)[1]} if k.startswith("like:") else {})
            for k in home_rows.order(keys, rows["used"], rows["newListener"])
        ]
        return out

    _like_cache: dict[tuple, list[int]] = {}

    def _taste_rows(conn, me_id: int, now: float) -> dict:
        """The rows of Home that come from your taste (see home.py)."""
        tracks = conn.execute(TRACK_SELECT).fetchall()
        plays = [(r[0], r[1]) for r in conn.execute(
            "SELECT track_id, played_at FROM plays WHERE user_id = ? AND played_at > ?", (me_id, now - 400 * 86400))]
        liked = {r[0] for r in conn.execute("SELECT track_id FROM likes WHERE user_id = ?", (me_id,))}
        mine = follows.followed(conn, me_id)
        taste = home_rows.artist_taste(tracks, mixes.affinity(plays, liked, now), mine)
        seed = mixes.day_seed(me_id, now)

        likes_rows = []
        stamp = (len(tracks), max((t["id"] for t in tracks), default=0))
        by_album = None
        for name in home_rows.seed_artists(taste, seed):
            key = (me_id, seed, videos.fold(name), stamp)
            ids = _like_cache.get(key)
            if ids is None:
                theirs = [t for t in tracks if credits.credited(t["album_artist_name"], name) or credits.credited(t["artist"], name)]
                own = {x["id"] for x in theirs}
                others = [t for t in tracks if t["id"] not in own]
                picks = _recommend(theirs, others, random.Random(seed).randrange(1, 10**6), 150)
                ids = home_rows.like_albums(picks, name)
                if len(_like_cache) > 200:
                    _like_cache.clear()
                _like_cache[key] = ids
            if len(ids) >= 4:
                if by_album is None:
                    by_album = {r["id"]: r for r in conn.execute("SELECT * FROM albums")}
                likes_rows.append((name, [album_json(by_album[i]) for i in ids if i in by_album]))

        following = []
        if mine:
            album_plays = {r[0]: r[1] for r in conn.execute(
                "SELECT album_key, COUNT(*) FROM plays WHERE user_id = ? GROUP BY album_key", (me_id,))}
            following = [album_json(a) for a in home_rows.following_albums(
                conn.execute("SELECT * FROM albums").fetchall(), mine, album_plays, now)]

        taps = [(r[0], r[1]) for r in conn.execute(
            "SELECT row, at FROM home_taps WHERE user_id = ? AND at > ?", (me_id, now - 120 * 86400))]
        recent_plays = sum(1 for _, at in plays if at > now - 30 * 86400)
        return {"like": likes_rows, "following": following, "used": home_rows.tap_scores(taps, now),
                "newListener": recent_plays < 20}

    @app.post("/api/home/used")
    def home_used(body: HomeUsedBody):
        """Something on Home was opened from this row; rows people use move up."""
        now = time.time()
        row = home_rows.kind(body.row)
        with db() as conn:
            # Browsing one row for a while counts once: it's coming back to a row that moves it.
            if conn.execute("SELECT 1 FROM home_taps WHERE user_id = ? AND row = ? AND at > ?",
                            (uid(), row, now - home_rows.TAP_GAP)).fetchone():
                return {"ok": True}
            conn.execute("INSERT INTO home_taps(user_id, row, at) VALUES(?, ?, ?)", (uid(), row, now))
            # Only the recent past counts; keep the table small.
            conn.execute("DELETE FROM home_taps WHERE user_id = ? AND at < ?", (uid(), now - 120 * 86400))
        return {"ok": True}

    @app.get("/api/tracks/{track_id}/resume")
    def get_resume(track_id: int):
        """Where you stopped in a long track (0: from the start)."""
        with db() as conn:
            if podcasts.is_episode(track_id):
                st = podcasts.state(conn, uid(), track_id - podcasts.EP_BASE)
                return {"position": st["position"] if st else 0}
            return {"position": resume.get(conn, uid(), track_id)}

    @app.put("/api/tracks/{track_id}/resume")
    def put_resume(track_id: int, body: ResumeBody):
        with db() as conn:
            if podcasts.is_episode(track_id):
                found = podcasts.episode(conn, track_id)
                if not found:
                    raise HTTPException(404, "Episode not found")
                podcasts.keep_place(conn, uid(), found[0]["id"], body.position, found[0]["duration"] or 0)
                return {"ok": True}
            row = conn.execute("SELECT duration FROM tracks WHERE id = ?", (track_id,)).fetchone()
            if not row:
                raise HTTPException(404, "Track not found")
            resume.put(conn, uid(), track_id, body.position, row["duration"] or 0)
        return {"ok": True}

    @app.post("/api/tracks/{track_id}/skipped")
    def skipped(track_id: int):
        """Moved on before 30 seconds of it (the apps send this; not in a private session)."""
        if podcasts.is_episode(track_id):
            return {"ok": True}  # podcasts don't teach the music recommenders
        with db() as conn:
            conn.execute("INSERT INTO feedback(user_id, track_id, kind, at) VALUES(?, ?, 'skip', ?)", (uid(), track_id, time.time()))
        return {"ok": True}

    @app.post("/api/tracks/{track_id}/played")
    def played(track_id: int, at: float | None = Query(None)):
        """A listen. `at`: when, for listens made offline and sent later (up to 60 days back)."""
        if podcasts.is_episode(track_id):
            return {"ok": True}  # episodes keep a place instead; they aren't music plays
        now = time.time()
        when = now if at is None or not (now - 60 * 86400 <= at <= now + 60) else min(at, now)
        with db() as conn:
            row = conn.execute("SELECT album_key FROM tracks WHERE id = ?", (track_id,)).fetchone()
            if not row:
                raise HTTPException(404, "Track not found")
            conn.execute(
                "INSERT INTO plays (track_id, album_key, played_at, user_id) VALUES (?, ?, ?, ?)",
                (track_id, row["album_key"], when, uid()),
            )
        scrobbler.queue(uid(), track_id, when)
        _tell_played(uid(), track_id)
        return {"ok": True}

    @app.get("/api/tracks/random")
    def random_tracks(limit: int = Query(100, ge=1, le=500), artist: str | None = None):
        with db() as conn:
            if not artist:
                rows = conn.execute(f"{TRACK_SELECT} ORDER BY RANDOM() LIMIT ?", (limit,)).fetchall()
            else:  # their songs, shared ones and features included
                rows = [r for r in conn.execute(f"{TRACK_SELECT} ORDER BY RANDOM()").fetchall()
                        if credits.credited(r["album_artist_name"], artist) or credits.credited(r["artist"], artist)][:limit]
        return [track_json(r) for r in rows]

    # ---------- streaming ----------

    def _track_file(track_id: int):
        with db() as conn:
            row = conn.execute("SELECT path, mtime, mime FROM tracks WHERE id = ?", (track_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Track not found")
        path = Path(row["path"])
        if not path.is_file():
            raise HTTPException(410, "File is missing; try rescanning the library")
        return path, row["mtime"], row["mime"]

    @app.get("/api/tracks/{track_id}/stream")
    async def stream(request: Request, track_id: int, q: str = "original"):
        if podcasts.is_episode(track_id):
            return await _episode_stream(request, track_id)
        path, mtime, mime = _track_file(track_id)
        if q == "original" and mime in NATIVE_MIMES:
            return FileResponse(path, media_type=mime, headers={"Cache-Control": "private, max-age=86400"})
        # Formats a browser can't play are sent as the best AAC tier instead.
        kbps = transcode.QUALITIES.get(q, transcode.QUALITIES["veryhigh"])
        out = transcode.cached(cfg.transcode_dir, path, mtime, kbps)
        if out:  # converted before: served whole, with seeking
            return FileResponse(out, media_type="audio/mp4", headers={"Cache-Control": "private, max-age=86400"})
        # The first time: sent while it's converted, so it starts at once.
        gen = transcode.stream_transcode(cfg.transcode_dir, path, mtime, kbps, cfg.transcode_cache_mb)
        try:
            first = await gen.__anext__()
        except (RuntimeError, StopAsyncIteration) as e:
            log.error("%s", e)
            raise HTTPException(500, "Could not convert this track")

        async def body():
            yield first
            try:
                async for chunk in gen:
                    yield chunk
            except RuntimeError as e:
                log.error("%s", e)

        return StreamingResponse(body(), media_type="audio/mp4", headers={"Cache-Control": "no-store"})

    @app.get("/api/tracks/{track_id}/lyrics")
    def track_lyrics(track_id: int, response: Response):
        if podcasts.is_episode(track_id):
            return {"kind": "none", "source": None, "searchedOnline": False}
        with db() as conn:
            row = conn.execute(
                "SELECT path, title, artist, album, duration FROM tracks WHERE id = ?", (track_id,)
            ).fetchone()
        if not row:
            raise HTTPException(404, "Track not found")
        result = lyrics.lyrics_for(cfg.db_path, row, cfg.online_lyrics)
        response.headers["Cache-Control"] = "private, max-age=600"
        return result

    # ---------- podcasts ----------

    async def _episode_stream(request: Request, track_id: int):
        """An episode, streamed from the show's host (seeking passed through), so the apps only
        ever talk to Shelf."""
        with db() as conn:
            found = podcasts.episode(conn, track_id)
        if not found:
            raise HTTPException(404, "Episode not found")
        try:
            upstream, keep, mime = await asyncio.to_thread(podcasts.open_episode, found[0], request.headers.get("range"))
        except podcasts.HostError as e:
            raise HTTPException(e.status, str(e))
        return StreamingResponse(podcasts.body(upstream), status_code=upstream.status, media_type=mime,
                                 headers={**keep, "Cache-Control": "no-store"})

    def _show_cover(pid: int, size: int):
        with db() as conn:
            show = conn.execute("SELECT * FROM podcasts WHERE id = ?", (pid,)).fetchone()
        art = podcasts.art_path(cfg.data_dir, show) if show else None
        path = covers.get_cover(cfg.cover_dir, f"file:{art}", size) if art else None
        if not path:
            raise HTTPException(404, "No cover")
        return FileResponse(path, media_type="image/webp", headers={"Cache-Control": "private, max-age=31536000, immutable"})

    def _my_shows(conn, me_id: int) -> list[dict]:
        rows = conn.execute(
            """SELECT p.*, COUNT(e.id) AS n, MAX(e.published_at) AS latest,
                      SUM(CASE WHEN COALESCE(st.finished, 0) = 0 THEN 1 ELSE 0 END) AS unplayed
               FROM podcasts p JOIN podcast_subs s ON s.podcast_id = p.id AND s.user_id = ?
               LEFT JOIN episodes e ON e.podcast_id = p.id
               LEFT JOIN episode_state st ON st.episode_id = e.id AND st.user_id = ?
               GROUP BY p.id ORDER BY latest DESC""", (me_id, me_id)).fetchall()
        return [podcasts.show_json(r, r["n"], r["unplayed"] or 0, r["latest"]) for r in rows]

    def _episode_rows(conn, me_id: int, where: str, params: tuple, limit: int, order: str = "e.published_at DESC") -> list[dict]:
        rows = conn.execute(
            f"""SELECT e.*, st.position AS st_position, st.finished AS st_finished, sv.saved_at AS sv_saved_at FROM episodes e
                LEFT JOIN episode_state st ON st.episode_id = e.id AND st.user_id = ?
                LEFT JOIN episode_saves sv ON sv.episode_id = e.id AND sv.user_id = ?
                WHERE {where} ORDER BY {order} LIMIT ?""", (me_id, me_id, *params, limit)).fetchall()
        shows = {}
        out = []
        for r in rows:
            show = shows.get(r["podcast_id"]) or conn.execute("SELECT * FROM podcasts WHERE id = ?", (r["podcast_id"],)).fetchone()
            shows[r["podcast_id"]] = show
            st = {"position": r["st_position"] or 0, "finished": r["st_finished"] or 0}
            out.append(podcasts.episode_json(r, show, st, r["sv_saved_at"]))
        return out

    @app.get("/api/podcasts")
    def my_podcasts():
        """The shows you follow, and the episodes to go on with: ones you're partway through, then
        new ones you haven't heard (from the last two weeks)."""
        me_id = uid()
        with db() as conn:
            shows = _my_shows(conn, me_id)
            mine = "e.podcast_id IN (SELECT podcast_id FROM podcast_subs WHERE user_id = ?)"
            going = _episode_rows(conn, me_id, f"{mine} AND st.position > 0 AND COALESCE(st.finished, 0) = 0", (me_id,), 20)
            fresh = _episode_rows(conn, me_id, f"{mine} AND COALESCE(st.finished, 0) = 0 AND COALESCE(st.position, 0) = 0 "
                                               "AND e.published_at > ?", (me_id, time.time() - 14 * 86400), 30)
            saved = conn.execute("SELECT COUNT(*) FROM episode_saves WHERE user_id = ?", (me_id,)).fetchone()[0]
        return {"shows": shows, "continue": going, "new": fresh, "saved": saved}

    @app.get("/api/podcasts/saved")
    def saved_episodes():
        """Your Episodes: the episodes you kept (or downloaded), the last one kept first."""
        me_id = uid()
        with db() as conn:
            episodes = _episode_rows(conn, me_id, "sv.saved_at IS NOT NULL", (), 2000, order="sv.saved_at DESC")
        return {"episodes": episodes}

    @app.get("/api/podcasts/search")
    async def find_podcasts(q: str = Query(..., min_length=2, max_length=500), live: bool = False):
        """Shows by name (Apple's podcast directory), or the show behind a pasted link. `live`:
        asked while someone types in the main search, which only searches the directory when
        online lookups are on (as for MusicBrainz), and not for a word or two. A pasted link is
        always read: that's how a show gets added with lookups off."""
        if live and not podcasts.looks_like_link(q) and (not cfg.artist_info or len(q.strip()) < 3):
            return {"results": [], "off": not cfg.artist_info}
        try:
            if podcasts.looks_like_link(q):
                link = q if q.lower().startswith("http") else f"https://{q}"
                feed = await asyncio.to_thread(podcasts.feed_for, link)
                show = await asyncio.to_thread(podcasts.fetch_show, feed)
                results = [{"title": show["title"], "author": show["author"], "feedUrl": feed, "image": show["image"],
                            "episodes": len(show["episodes"])}]
            else:
                results = await asyncio.to_thread(podcasts.search, q)
        except podcasts.FeedError as e:
            return {"results": [], "error": str(e)}
        except urllib.error.HTTPError as e:
            return {"results": [], "error": "That show’s feed is gone." if e.code in (404, 410)
                    else f"The podcast’s host said no ({e.code})."}
        except (OSError, ValueError):
            return {"results": [], "error": "Couldn’t reach that. Check the link, or try again in a moment."}
        with db() as conn:
            have = {r[0]: r[1] for r in conn.execute(
                "SELECT p.feed_url, p.id FROM podcasts p JOIN podcast_subs s ON s.podcast_id = p.id AND s.user_id = ?", (uid(),))}
        return {"results": [r | {"following": r["feedUrl"] in have, "id": have.get(r["feedUrl"])} for r in results]}

    @app.post("/api/podcasts")
    async def add_podcast(body: PodcastBody):
        """Follow a show by its feed."""
        feed = body.feedUrl.strip()
        try:
            show = await asyncio.to_thread(podcasts.fetch_show, feed)
        except podcasts.FeedError as e:
            raise HTTPException(400, str(e))
        except urllib.error.HTTPError as e:
            raise HTTPException(400, "That show’s feed is gone." if e.code in (404, 410) else f"The podcast’s host said no ({e.code}).")
        except (OSError, ValueError):
            raise HTTPException(502, "Couldn’t reach that podcast. Try again in a moment.")
        with db() as conn:
            pid = podcasts.store(conn, feed, show)
            podcasts.follow(conn, uid(), pid)
        return _podcast_page(pid)

    def _podcast_page(pid: int, limit: int = 300) -> dict:
        me_id = uid()
        with db() as conn:
            show = conn.execute("SELECT * FROM podcasts WHERE id = ?", (pid,)).fetchone()
            if not show:
                raise HTTPException(404, "Podcast not found")
            mine = pid in podcasts.following(conn, me_id)
            n = conn.execute("SELECT COUNT(*) FROM episodes WHERE podcast_id = ?", (pid,)).fetchone()[0]
            episodes = _episode_rows(conn, me_id, "e.podcast_id = ?", (pid,), limit)
        unplayed = sum(1 for e in episodes if not e["finished"])
        latest = episodes[0]["published"] if episodes else None
        return podcasts.show_json(show, n, unplayed, latest, following_it=mine) | {"episodeList": episodes}

    @app.get("/api/podcasts/{pid}")
    def podcast_page(pid: int):
        return _podcast_page(pid)

    @app.delete("/api/podcasts/{pid}")
    def unfollow_podcast(pid: int):
        with db() as conn:
            podcasts.unfollow(conn, uid(), pid)
        return {"ok": True}

    @app.post("/api/podcasts/{pid}/refresh")
    async def refresh_podcast(pid: int):
        with db() as conn:
            if pid not in podcasts.following(conn, uid()):
                raise HTTPException(404, "Podcast not found")
        new = await asyncio.to_thread(podcasts.refresh, cfg.db_path, pid)
        return _podcast_page(pid) | {"new": new}

    @app.put("/api/podcasts/episodes/{eid}")
    def mark_episode(eid: int, body: EpisodeBody):
        """Mark an episode finished, or not (back to unheard)."""
        with db() as conn:
            if not conn.execute("SELECT 1 FROM episodes WHERE id = ?", (eid,)).fetchone():
                raise HTTPException(404, "Episode not found")
            podcasts.mark(conn, uid(), eid, body.finished)
        return {"ok": True, "finished": body.finished}

    @app.put("/api/podcasts/episodes/{eid}/saved")
    def save_episode(eid: int):
        """Keep an episode in Your Episodes."""
        with db() as conn:
            if not conn.execute("SELECT 1 FROM episodes WHERE id = ?", (eid,)).fetchone():
                raise HTTPException(404, "Episode not found")
            podcasts.save(conn, uid(), eid, True)
        return {"ok": True, "saved": True}

    @app.delete("/api/podcasts/episodes/{eid}/saved")
    def unsave_episode(eid: int):
        with db() as conn:
            podcasts.save(conn, uid(), eid, False)
        return {"ok": True, "saved": False}

    # ---------- music videos ----------

    @app.get("/api/tracks/{track_id}/video")
    def track_video(track_id: int, response: Response):
        if podcasts.is_episode(track_id):
            return {"found": False}
        with db() as conn:
            row = conn.execute("SELECT title, artist, duration FROM tracks WHERE id = ?", (track_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Track not found")
        hit = videos.video_for(cfg.db_path, row["artist"], row["title"], row["duration"] or 0) if cfg.music_videos else None
        response.headers["Cache-Control"] = "private, max-age=600"
        return {"found": bool(hit), **(hit or {})}

    # ---------- artist page ----------

    _COMPILATION = re.compile(
        r"\b(greatest hits|best of|the best|hits|collection|anthology|essentials?|definitive|gold|"
        r"singles|b-sides|rarities|retrospective|years)\b", re.I)

    def _release_kind(a) -> str:
        """Album, single, EP or compilation, guessed from the title, song count and length."""
        # Libraries often say so in the title: "Duality (Single)", "Antennas To Hell (Compilation)".
        tags = " ".join(re.findall(r"\(([^)]*)\)", a["title"])).casefold()
        if "compilation" in tags or _COMPILATION.search(a["title"]):
            return "compilation"
        if re.search(r"\b(single|promo)\b", tags):
            return "single"
        if re.search(r"\bep\b", tags):
            return "ep"
        n, mins = a["track_count"], (a["duration"] or 0) / 60
        if n <= 3 and mins < 20:
            return "single"
        if n <= 7 and mins < 32:
            return "ep"
        return "album"

    @app.get("/api/artist")
    def artist_page(name: str = Query(..., min_length=1, max_length=200)):
        """Everything on an artist page: releases, their most played songs, albums they
        appear on, and playlists with their songs. Plays are everyone's on this server added up
        (a total says nothing about who played what); playlists are the viewer's."""
        me_id = uid()
        with db() as conn:
            # Their albums, shared ones too: "Aerosmith & Yungblud" is on both pages.
            albums = [a for a in conn.execute(
                """SELECT a.*, COUNT(p.id) AS plays, MAX(p.played_at) AS last_played
                   FROM albums a LEFT JOIN plays p ON p.album_key = a.key
                   GROUP BY a.id ORDER BY COALESCE(a.year, 9999) DESC, a.title COLLATE NOCASE""",
            ).fetchall() if credits.credited(a["artist"], name)]
            # Songs credited to the artist, on their own albums or others' (features too).
            keys = [a["key"] for a in albums]
            credits_with = [c for (c,) in conn.execute("SELECT DISTINCT artist FROM tracks") if credits.credited(c, name)]
            rows = conn.execute(
                f"""SELECT t.*, a.id AS album_id, a.title AS album_title, a.artist AS album_artist_name, a.cover_src,
                           (SELECT COUNT(*) FROM plays p WHERE p.track_id = t.id) AS plays,
                           (SELECT MAX(played_at) FROM plays p WHERE p.track_id = t.id) AS last_played
                    FROM tracks t JOIN albums a ON a.key = t.album_key
                    WHERE a.key IN ({','.join('?' * len(keys)) or 'NULL'})
                       OR t.artist IN ({','.join('?' * len(credits_with)) or 'NULL'})""",
                (*keys, *credits_with),
            ).fetchall()
            tracks = list(rows)
            if not albums and not tracks:
                raise HTTPException(404, "No music by this artist")
            ids = [t["id"] for t in tracks]
            playlists = []
            if ids:
                marks = ",".join("?" * len(ids))
                for r in conn.execute(
                    f"""SELECT e.playlist_id, COUNT(*) AS n FROM playlist_tracks e
                        JOIN playlists p ON p.id = e.playlist_id AND p.user_id = ?
                        WHERE e.track_id IN ({marks})
                        GROUP BY e.playlist_id ORDER BY n DESC LIMIT 12""", [me_id, *ids],
                ).fetchall():
                    s = _playlist_summary(conn, r["playlist_id"])
                    if s:
                        playlists.append(s | {"artistCount": r["n"]})
            own = {a["id"] for a in albums}
            others = sorted({t["album_id"] for t in tracks} - own)
            appears = conn.execute(
                f"""SELECT * FROM albums WHERE id IN ({','.join('?' * len(others)) or 'NULL'})
                    ORDER BY COALESCE(year, 0) DESC""", others,
            ).fetchall()

        # Popular: the most played songs, then (for songs never played) a spread of each
        # album's opening tracks, newest album first, so the list is never empty.
        played = sorted((t for t in tracks if t["plays"]), key=lambda t: (-t["plays"], -(t["last_played"] or 0)))
        order = {a["id"]: i for i, a in enumerate(albums)}
        # Songs they're featured on come after their own.
        rest = sorted((t for t in tracks if not t["plays"]),
                      key=lambda t: (t["album_id"] not in order, t["track_no"] or 99, order.get(t["album_id"], 0)))
        popular = (played + rest)[:10]
        display = credits.display(name)
        total_plays = sum(t["plays"] for t in tracks)
        mine = [t for t in tracks if t["album_id"] in order]
        with db() as conn:
            following = follows.is_following(conn, me_id, display)
        return {
            "name": display,
            "following": following,
            "albums": [album_json(a) | {"plays": a["plays"], "kind": _release_kind(a)} for a in albums],
            "popular": [track_json(t) | {"plays": t["plays"]} for t in popular],
            "appearsOn": [album_json(a) for a in appears],
            "playlists": playlists,
            "stats": {
                "albums": len(albums), "songs": len(mine), "duration": round(sum(t["duration"] for t in mine)),
                "plays": total_plays, "songsPlayed": sum(1 for t in tracks if t["plays"]),
                "lastPlayed": max((t["last_played"] or 0 for t in tracks), default=0) or None,
            },
        }

    # ---------- about the artist ----------

    def _artist_names(name: str) -> list[str]:
        """The name, then each artist of a shared credit ("Aerosmith & Yungblud")."""
        parts = [p.strip() for p in re.split(r"\s+(?:&|and|x|feat\.?|ft\.?|with)\s+|,\s*", name, flags=re.I) if p.strip()]
        return [name] + [p for p in parts if p.casefold() != name.casefold()]

    @app.get("/api/artist/about")
    def artist_about(name: str = Query(..., min_length=1, max_length=200)):
        if not cfg.artist_info:
            return {"found": False}
        for n in _artist_names(name):
            data = artist_info.about(cfg.db_path, cfg.data_dir, n)
            if data:
                img = f"api/artist/image?name={urllib.parse.quote(n)}" if data.get("hasImage") else None
                if img and "color" not in data:
                    # The photo's accent color tints the artist page, as a cover tints an album page.
                    data["color"] = covers.accent_color(artist_info.image_path(cfg.data_dir, n))
                    artist_info.store(cfg.db_path, videos.fold(n), "about", data)
                return {"found": True, **data, "image": img}
        return {"found": False}

    @app.get("/api/artist/image")
    def artist_image(name: str = Query(..., min_length=1, max_length=200)):
        path = artist_info.image_path(cfg.data_dir, name)
        if not path.is_file():
            raise HTTPException(404, "No photo")
        return FileResponse(path, media_type="image/webp", headers={"Cache-Control": "private, max-age=604800"})

    @app.get("/api/artist/videos")
    def artist_videos(name: str = Query(..., min_length=1, max_length=200)):
        if not cfg.music_videos:
            return []
        for n in _artist_names(name):
            found = videos.artist_videos(cfg.db_path, n)
            if found:
                return found
        return []

    # ---------- playlists ----------

    def _playlist_summary(conn, pid: int) -> dict | None:
        p = conn.execute(
            """SELECT p.*, COUNT(e.id) AS n, COALESCE(SUM(t.duration), 0) AS dur, u.username AS owner_name,
                      (SELECT 1 FROM playlist_follows f WHERE f.playlist_id = p.id AND f.user_id = ?) AS following,
                      (SELECT COUNT(*) FROM playlist_follows f WHERE f.playlist_id = p.id) AS followers
               FROM playlists p LEFT JOIN playlist_tracks e ON e.playlist_id = p.id
               LEFT JOIN tracks t ON t.id = e.track_id LEFT JOIN users u ON u.id = p.user_id
               WHERE p.id = ? GROUP BY p.id""",
            (uid(), pid),
        ).fetchone()
        if not p:
            return None
        rules = _rules_of(p)
        if rules:  # a smart playlist: what its rules pick now
            picked = _smart_rows(conn, p["id"], rules, uid())
            n, dur = len(picked), sum(r["duration"] or 0 for r in picked)
            seen, covers_rows = set(), []
            for r in picked:
                if r["cover_src"] and r["album_id"] not in seen and len(covers_rows) < 4:
                    seen.add(r["album_id"])
                    covers_rows.append({"id": r["album_id"], "cover_src": r["cover_src"]})
        else:
            n, dur = p["n"], p["dur"]
            # Up to four different album covers, in playlist order, for the mosaic.
            covers_rows = conn.execute(
                """SELECT a.id, a.cover_src, MIN(e.position) AS pos FROM playlist_tracks e
                   JOIN tracks t ON t.id = e.track_id JOIN albums a ON a.key = t.album_key
                   WHERE e.playlist_id = ? AND a.cover_src IS NOT NULL
                   GROUP BY a.id ORDER BY pos LIMIT 4""",
                (pid,),
            ).fetchall()
        return {
            "id": p["id"], "name": p["name"], "description": p["description"],
            "trackCount": n, "duration": round(dur, 1),
            "covers": [{"albumId": r["id"], "cover": _cover_version(r["cover_src"])} for r in covers_rows],
            "createdAt": p["created_at"], "updatedAt": p["updated_at"], "mix": bool(p["mix"]),
            "smart": rules, "rulesText": smart.describe(rules) if rules else None,
            "shared": p["shared"], "mine": p["user_id"] == uid(),
            "canEdit": not rules and (p["user_id"] == uid() or p["shared"] == 2),
            "owner": {"id": p["user_id"], "username": p["owner_name"] or "Someone"},
            "following": bool(p["following"]), "followers": p["followers"],
        }

    def _rules_of(p) -> dict | None:
        try:
            return smart.validate(json.loads(p["rules"])) if p["rules"] else None
        except (ValueError, TypeError):
            return None

    def _smart_rows(conn, pid: int, rules: dict, user_id: int) -> list:
        """The songs a smart playlist's rules pick for this person, now."""
        rows = conn.execute(TRACK_SELECT).fetchall()
        facts = smart.Facts(likes={r[0] for r in conn.execute("SELECT track_id FROM likes WHERE user_id = ?", (user_id,))})
        for r in conn.execute("SELECT track_id, COUNT(*), MAX(played_at) FROM plays WHERE user_id = ? GROUP BY track_id", (user_id,)):
            facts.plays[r[0]], facts.last[r[0]] = r[1], r[2]
        if smart.uses_moods(rules):
            facts.moods = smart.mood_sets(rows, sound.energy(rows))
        now = time.time()
        ids = smart.songs(rows, facts, rules, now, seed=f"smart:{pid}:{int(now // 86400)}")
        by_id = {r["id"]: r for r in rows}
        return [by_id[i] for i in ids]

    def _not_smart(conn, pid: int) -> None:
        row = conn.execute("SELECT rules FROM playlists WHERE id = ?", (pid,)).fetchone()
        if row and row["rules"]:
            raise HTTPException(400, "This is a smart playlist: its rules pick the songs. Edit the rules to change them.")

    def _set_rules(conn, pid: int, rules: dict) -> None:
        try:
            checked = smart.validate(rules)
        except ValueError as e:
            raise HTTPException(400, str(e))
        conn.execute("UPDATE playlists SET rules = ? WHERE id = ?", (json.dumps(checked), pid))

    def _touch(conn, pid: int) -> None:
        conn.execute("UPDATE playlists SET updated_at = ? WHERE id = ?", (time.time(), pid))

    def _require_playlist(conn, pid: int, need: str = "owner") -> None:
        """404 unless the signed-in person may do this to the playlist. `need`: "read" (theirs, or
        shared), "tracks" (theirs, or collaborative: add, remove, reorder) or "owner"."""
        p = conn.execute("SELECT user_id, shared FROM playlists WHERE id = ?", (pid,)).fetchone()
        mine = p is not None and p["user_id"] == uid()
        if p is None or not (mine or (need == "read" and p["shared"] >= 1) or (need == "tracks" and p["shared"] == 2)):
            if p is not None and p["shared"] >= 1 and need != "read":
                raise HTTPException(403, "Only the person who made this playlist can change it")
            raise HTTPException(404, "Playlist not found")

    def _append(conn, pid: int, track_ids: list[int], suggested: bool = False) -> int:
        known = {r["id"] for r in conn.execute(
            f"SELECT id FROM tracks WHERE id IN ({','.join('?' * len(track_ids))})", track_ids)} if track_ids else set()
        start = conn.execute("SELECT COALESCE(MAX(position), 0) FROM playlist_tracks WHERE playlist_id = ?", (pid,)).fetchone()[0]
        now = time.time()
        me_id = uid()
        rows = [(pid, tid, start + i + 1, now, me_id, int(suggested)) for i, tid in enumerate(t for t in track_ids if t in known)]
        conn.executemany("INSERT INTO playlist_tracks(playlist_id, track_id, position, added_at, added_by, suggested) "
                         "VALUES(?, ?, ?, ?, ?, ?)", rows)
        return len(rows)

    @app.get("/api/playlists")
    def list_playlists():
        with db() as conn:
            # Your own, and other people's you follow (while they're still shared).
            ids = [r["id"] for r in conn.execute(
                """SELECT p.id FROM playlists p WHERE p.user_id = ?1
                   OR (p.shared >= 1 AND p.id IN (SELECT playlist_id FROM playlist_follows WHERE user_id = ?1))
                   ORDER BY p.updated_at DESC""", (uid(),))]
            return [_playlist_summary(conn, i) for i in ids]

    @app.post("/api/playlists")
    def create_playlist(body: PlaylistBody):
        now = time.time()
        with db() as conn:
            name = (body.name or "").strip()
            if not name:
                n = conn.execute("SELECT COUNT(*) FROM playlists WHERE user_id = ?", (uid(),)).fetchone()[0]
                name = f"My Playlist #{n + 1}"
            pid = conn.execute(
                "INSERT INTO playlists(name, description, created_at, updated_at, user_id) VALUES(?, ?, ?, ?, ?)",
                (name, (body.description or "").strip(), now, now, uid()),
            ).lastrowid
            if body.rules is not None:
                _set_rules(conn, pid, body.rules)
            else:
                _append(conn, pid, body.trackIds)
            return _playlist_summary(conn, pid)

    @app.post("/api/playlists/import")
    def import_playlists(body: ImportBody):
        """The songs of a playlist from elsewhere (a Spotify or YouTube link, a playlist file, a CSV
        export, a pasted list), each with the library's song for it or null. Nothing is saved: the
        app makes the playlist from the songs that were found."""
        text = body.text.strip()
        if not text:
            raise HTTPException(400, "Paste a link or a list of songs, or choose a file.")
        try:
            found = [imports.fetch(text)] if imports.link(text) else imports.parse_file(body.text, body.filename)
        except ValueError as e:
            raise HTTPException(400, str(e))
        if not found:
            raise HTTPException(400, "Shelf couldn’t find any songs in that.")
        with db() as conn:
            library = imports.Library(conn.execute(
                "SELECT t.id, t.title, t.artist, t.album_artist, t.album, t.duration, t.path FROM tracks t"))
            out = []
            for p in found:
                ids = [library.find(w) for w in p["songs"]]
                rows = {r["id"]: r for r in conn.execute(
                    f"{TRACK_SELECT} WHERE t.id IN ({','.join('?' * len(set(ids) - {None}))})",
                    [i for i in set(ids) if i is not None])} if any(ids) else {}
                songs = [{"want": imports.label(w), "track": track_json(rows[i]) if i in rows else None}
                         for w, i in zip(p["songs"], ids)]
                out.append({"name": p["name"][:200], "found": sum(1 for s in songs if s["track"]), "songs": songs})
        return {"playlists": out, "linked": bool(imports.link(text))}

    @app.post("/api/smart/preview")
    def smart_preview(body: dict):
        """How many songs some smart playlist rules pick right now, and the rules in words."""
        try:
            rules = smart.validate(body.get("rules"))
        except ValueError as e:
            raise HTTPException(400, str(e))
        with db() as conn:
            picked = _smart_rows(conn, 0, rules, uid())
        return {"count": len(picked), "duration": round(sum(r["duration"] or 0 for r in picked)),
                "text": smart.describe(rules)}

    @app.get("/api/playlists/{pid}")
    def get_playlist(pid: int):
        with db() as conn:
            _require_playlist(conn, pid, "read")
            summary = _playlist_summary(conn, pid)
            if not summary:
                raise HTTPException(404, "Playlist not found")
            if summary["smart"]:
                return {**summary, "tracks": [track_json(r) for r in _smart_rows(conn, pid, summary["smart"], uid())]}
            rows = conn.execute(
                f"""SELECT e.id AS entry_id, e.added_at AS entry_added, e.transition, u.username AS added_by_name, q.*
                    FROM playlist_tracks e JOIN ({TRACK_SELECT}) q ON q.id = e.track_id
                    LEFT JOIN users u ON u.id = e.added_by
                    WHERE e.playlist_id = ? ORDER BY e.position""",
                (pid,),
            ).fetchall()
        tracks = [{**track_json(r), "entryId": r["entry_id"], "addedAt": r["entry_added"],
                   "addedBy": r["added_by_name"], "transition": transition_json(r["transition"])} for r in rows]
        return {**summary, "tracks": tracks}

    @app.get("/api/playlists/{pid}/recommendations")
    def recommendations(pid: int, seed: int = 0, limit: int = Query(10, ge=1, le=50)):
        """Songs from the library that fit a playlist: its artists and genres, and tempos
        and keys that sit well with its songs. `seed` shuffles near-ties (Refresh)."""
        with db() as conn:
            _require_playlist(conn, pid, "read")
            if conn.execute("SELECT rules FROM playlists WHERE id = ?", (pid,)).fetchone()["rules"]:
                return []  # a smart playlist's rules pick its songs
            mine = conn.execute(
                f"""SELECT q.* FROM playlist_tracks e JOIN ({TRACK_SELECT}) q ON q.id = e.track_id
                    WHERE e.playlist_id = ?""", (pid,)).fetchall()
            if not mine:
                return []
            pool = conn.execute(
                f"""{TRACK_SELECT} WHERE t.id NOT IN (SELECT track_id FROM playlist_tracks WHERE playlist_id = ?)""",
                (pid,)).fetchall()
        return _recommend(mine, pool, seed, limit, playlist_id=pid)

    @app.post("/api/playlists/make")
    def make_playlist(body: MakeBody):
        """A playlist's songs from a few words ("metal, high energy", "chill 90s", "like Metallica").
        Nothing is saved: the app creates the playlist with these songs."""
        me_id = uid()
        now = time.time()
        with db() as conn:
            rows = conn.execute(TRACK_SELECT).fetchall()
            plays = [(r[0], r[1]) for r in conn.execute(
                "SELECT track_id, played_at FROM plays WHERE user_id = ? AND played_at > ?", (me_id, now - 400 * 86400))]
            liked = {r[0] for r in conn.execute("SELECT track_id FROM likes WHERE user_id = ?", (me_id,))}
        known = releases.artist_genres(cfg.db_path)
        artists = sorted({a for r in rows for a in (r["artist"], r["album_artist_name"]) if a})
        want = playlist_maker.understand(body.prompt, genres.library_genres(rows, known), artists)
        if want.empty:
            raise HTTPException(400, "Shelf didn’t recognise any of that. Try a genre, an artist, a mood (workout, "
                                     "chill, party, feel good, melancholy, heavy), “high energy” or a decade like 90s.")
        ids = playlist_maker.make(rows, sound.energy(rows), mixes.affinity(plays, liked, now), want, _recommend,
                                  size=body.size, seed=f"{me_id}:{now}", genres_of=lambda r: genres.song_genres(r, known))
        if not ids:
            raise HTTPException(400, "Nothing on your shelf fits all of that. Try fewer words.")
        name = body.prompt.strip()
        return {"name": name[:1].upper() + name[1:], "understood": playlist_maker.describe(want), "trackIds": ids}

    @app.post("/api/suggest")
    def suggest(body: SuggestBody):
        """Songs that fit a set of songs (Smart Shuffle, the Add to playlist panel)."""
        with db() as conn:
            ids = body.trackIds[:500]
            if not ids:
                return []
            mine = conn.execute(f"{TRACK_SELECT} WHERE t.id IN ({','.join('?' * len(ids))})", ids).fetchall()
            skip = set(body.exclude) | set(ids)
            pool = [r for r in conn.execute(TRACK_SELECT).fetchall() if r["id"] not in skip]
        return _recommend(mine, pool, body.seed, body.limit)

    def _turned_down(playlist_id: int | None):
        """This person's skips and removed suggestions, as penalties (see feedback.py)."""
        try:
            me_id = uid()
        except Exception:  # outside a request (no one to learn from)
            return {}, {}, set()
        with db() as conn:
            rows = conn.execute(
                """SELECT f.track_id, COALESCE(a.artist, t.artist) AS artist, f.kind, f.playlist_id, f.at
                   FROM feedback f JOIN tracks t ON t.id = f.track_id JOIN albums a ON a.key = t.album_key
                   WHERE f.user_id = ? AND f.at > ?""", (me_id, time.time() - feedback.REMEMBER)).fetchall()
        return feedback.penalties([(r[0], videos.fold(r[1] or ""), r[2], r[3], r[4]) for r in rows], time.time(), playlist_id)

    def _recommend(mine, pool, seed: int, limit: int, playlist_id: int | None = None) -> list[dict]:
        """Score `pool` by how well each song fits `mine`: shared artists and genres, and
        tempos and keys that sit well together. `seed` shuffles near-ties (Refresh)."""
        if not mine:
            return []
        fold = videos.fold
        known = releases.artist_genres(cfg.db_path)  # MusicBrainz's, per artist, besides the tags
        artist_n, genre_n, album_ids = {}, {}, set()
        for t in mine:
            for a in {fold(t["artist"]), fold(t["album_artist_name"] or "")} - {""}:
                artist_n[a] = artist_n.get(a, 0) + 1
            for g in genres.song_genres(t, known):
                genre_n[g] = genre_n.get(g, 0) + 1
            album_ids.add(t["album_id"])
        bpms = [t["bpm"] for t in mine if t["bpm"]]
        mine_ids = [t["id"] for t in mine]
        # Sounds like: how close each song is to the songs of `mine` it's nearest to.
        near = sound.nearest(sound.vectors([*mine, *pool]), mine_ids, [t["id"] for t in pool])
        # Belongs together: shares playlists or listening sessions with them.
        with_them = together.scores(*together.load(cfg.db_path), set(mine_ids))
        keys = {analysis.camelot(t["musical_key"]) for t in mine} - {None}
        friendly = set().union(*(analysis.camelot_neighbours(k) for k in keys)) if keys else set()
        song_down, artist_down, banned = _turned_down(playlist_id)
        rng = random.Random(seed)
        scored = []
        for t in pool:
            if t["id"] in banned:
                continue
            a = max(artist_n.get(fold(t["artist"]), 0), artist_n.get(fold(t["album_artist_name"] or ""), 0))
            s = 3 * min(a, 5) / 5 + (1.2 if a else 0)
            if genre_n:
                shared = [genre_n.get(g, 0) for g in genres.song_genres(t, known)]
                if shared:
                    s += 2 * max(shared) / len(mine)
            if t["bpm"] and bpms:
                d = min(min(abs(t["bpm"] - b), abs(2 * t["bpm"] - b), abs(t["bpm"] - 2 * b)) for b in bpms)
                s += 1.5 * max(0.0, 1 - d / 15)
            if friendly and analysis.camelot(t["musical_key"]) in friendly:
                s += 1
            if t["album_id"] in album_ids:
                s += 0.4
            s += 3 * max(0.0, near.get(t["id"], 0.0))
            s += 2.5 * with_them.get(t["id"], 0.0)
            s -= song_down.get(t["id"], 0.0) + artist_down.get(fold(t["album_artist_name"] or t["artist"] or ""), 0.0)
            s += rng.random() * (1.6 if seed else 0.3)
            scored.append((s, t))
        scored.sort(key=lambda x: -x[0])
        # Variety: songs by the artists already there take at most a fifth of the places (at
        # least two), and any other artist at most two, so the rest is music that fits rather
        # than more of the same bands. Only when nothing else fits do the held-back songs fill up.
        own_cap = max(2, limit // 5)
        out, held, per_album, per_artist, own = [], [], {}, {}, 0
        for _s, t in scored:
            al, ar = t["album_id"], fold(t["artist"])
            mine_artist = ar in artist_n or fold(t["album_artist_name"] or "") in artist_n
            if per_album.get(al, 0) >= 2 or per_artist.get(ar, 0) >= 2 or (mine_artist and own >= own_cap):
                held.append(t)
                continue
            per_album[al] = per_album.get(al, 0) + 1
            per_artist[ar] = per_artist.get(ar, 0) + 1
            own += mine_artist
            out.append(track_json(t))
            if len(out) >= limit:
                return out
        return out + [track_json(t) for t in held[:limit - len(out)]]

    # ---------- sharing ----------

    @app.put("/api/playlists/{pid}/follow")
    def follow_playlist(pid: int):
        with db() as conn:
            _require_playlist(conn, pid, "read")
            conn.execute("INSERT OR IGNORE INTO playlist_follows(user_id, playlist_id, followed_at) VALUES(?, ?, ?)",
                         (uid(), pid, time.time()))
            return _playlist_summary(conn, pid)

    @app.delete("/api/playlists/{pid}/follow")
    def unfollow_playlist(pid: int):
        with db() as conn:
            conn.execute("DELETE FROM playlist_follows WHERE user_id = ? AND playlist_id = ?", (uid(), pid))
        return {"ok": True}

    @app.get("/api/playlists-shared")
    def shared_playlists():
        """Other people's public and collaborative playlists, newest changes first."""
        with db() as conn:
            ids = [r["id"] for r in conn.execute(
                "SELECT id FROM playlists WHERE shared >= 1 AND user_id != ? ORDER BY updated_at DESC LIMIT 30", (uid(),))]
            return [s for s in (_playlist_summary(conn, i) for i in ids) if s and s["trackCount"]]

    @app.get("/api/stats")
    def listening_stats(period: str = Query("year", pattern=r"^(month|year|all|\d{4})$"),
                        tz: int = Query(0, ge=-840, le=840)):
        """Your listening: totals, tops, when you listen, streaks, On this day, and the years there
        are to look back on (Wrapped). `tz`: the app's offset from UTC in minutes (east positive)."""
        me_id = uid()
        now = time.time()
        with db() as conn:
            plays = [(r[0], r[1]) for r in conn.execute("SELECT track_id, played_at FROM plays WHERE user_id = ?", (me_id,))]
            rows = {r["id"]: r for r in conn.execute(TRACK_SELECT)}
            known = releases.artist_genres(cfg.db_path)
            s = stats.summary(plays, rows, lambda t: genres.song_genres(t, known), tz, period, now)
            album_ids = [a["albumId"] for a in s["topAlbums"]]
            albums = {a["id"]: a for a in conn.execute(
                f"SELECT * FROM albums WHERE id IN ({','.join('?' * len(album_ids)) or 'NULL'})", album_ids)}
        s["topSongs"] = [track_json(rows[x["id"]]) | {"plays": x["plays"]} for x in s["topSongs"]]
        s["topAlbums"] = [album_json(albums[x["albumId"]]) | {"plays": x["plays"]} for x in s["topAlbums"] if x["albumId"] in albums]
        s["onThisDay"] = [track_json(rows[i]) for i in stats.on_this_day(plays, tz, now)[:10] if i in rows]
        s["years"] = stats.years(plays, tz)
        return s

    @app.get("/api/activity")
    def friend_activity():
        """What everyone else on this server is playing, or played last (unless they keep it to
        themselves, or are in a private session)."""
        me_id = uid()
        now = time.time()
        out = []
        with db() as conn:
            people = conn.execute(
                "SELECT id, username FROM users WHERE id != ? AND share_activity = 1", (me_id,)).fetchall()
            for u in people:
                live = None
                hub = hubs.get(u["id"])
                st = hub.state if hub and hub.active and hub.active in hub.devices else None
                if st and st.get("track") and not st.get("private"):
                    t = st["track"]
                    dev = hub.devices.get(hub.active)
                    live = {"track": t, "playing": bool(st.get("playing")), "context": st.get("context"),
                            "device": dev.name if dev else None}
                last = conn.execute(
                    f"""SELECT p.played_at, q.* FROM plays p JOIN ({TRACK_SELECT}) q ON q.id = p.track_id
                        WHERE p.user_id = ? ORDER BY p.played_at DESC LIMIT 1""", (u["id"],)).fetchone()
                if not live and not last:
                    continue
                out.append({
                    "user": {"id": u["id"], "username": u["username"]},
                    "now": live,
                    "last": {"track": track_json(last), "at": last["played_at"]} if last else None,
                    "sort": now if live and live["playing"] else (last["played_at"] if last else 0),
                })
        out.sort(key=lambda x: -x["sort"])
        return out

    @app.get("/api/people")
    def people():
        """Everyone else on this server, for Blend."""
        with db() as conn:
            rows = conn.execute("SELECT id, username, share_activity FROM users WHERE id != ? ORDER BY username COLLATE NOCASE",
                                (uid(),)).fetchall()
        return [{"id": r["id"], "username": r["username"], "canBlend": bool(r["share_activity"])} for r in rows]

    @app.get("/api/blend/{other_id}")
    def blend(other_id: int):
        """A playlist for two: songs each of you loves, songs you both play, and songs that fit
        you both, with how close your tastes are."""
        me_user = me()
        now = time.time()
        with db() as conn:
            other = conn.execute("SELECT id, username, share_activity FROM users WHERE id = ?", (other_id,)).fetchone()
            if not other or other_id == me_user.id:
                raise HTTPException(404, "No such person")
            if not other["share_activity"]:
                raise HTTPException(403, f"{other['username']} keeps their listening to themselves")
            rows = conn.execute(TRACK_SELECT).fetchall()

            def taste(user_id):
                plays = [(r[0], r[1]) for r in conn.execute(
                    "SELECT track_id, played_at FROM plays WHERE user_id = ? AND played_at > ?", (user_id, now - 400 * 86400))]
                liked = {r[0] for r in conn.execute("SELECT track_id FROM likes WHERE user_id = ?", (user_id,))}
                return mixes.affinity(plays, liked, now)
            mine, theirs = taste(me_user.id), taste(other_id)
        result = mixes.blend(rows, mine, theirs, _recommend, f"{min(me_user.id, other_id)}:{max(me_user.id, other_id)}:{mixes.day_seed(0, now)}")
        tracks = [(t if isinstance(t, dict) else track_json(t)) | {"blendFor": who} for t, who in result["tracks"]]
        names = sorted([me_user.username, other["username"]], key=str.casefold)
        return {"key": f"blend-{other_id}", "kind": "blend", "name": f"{names[0]} + {names[1]}", "with": other["username"],
                "description": f"A Blend of your tastes. You’re a {result['match']}% taste match"
                               if result["match"] is not None else
                               "A Blend of your tastes. It gets better the more you both play",
                "match": result["match"], "color": "#d6336c", "tracks": tracks,
                "covers": _covers_of(tracks), "trackCount": len(tracks)}

    # ---------- made for you ----------

    def _covers_of(tracks: list[dict], prefer: list[str] | None = None) -> list[dict]:
        """Up to four album covers, the mix's own artists first."""
        want = {videos.fold(a) for a in prefer or []}
        order = sorted(tracks, key=lambda t: not any(
            videos.fold(n) in want for n in (t.get("albumArtists") or t.get("artists") or [t["artist"]])))
        seen, out = set(), []
        for t in order:
            if t["cover"] and t["albumId"] not in seen:
                seen.add(t["albumId"])
                out.append({"albumId": t["albumId"], "cover": t["cover"]})
            if len(out) == 4:
                break
        return out

    _mix_cache: dict[tuple, dict] = {}

    def _made_for_you(me_id: int) -> dict[str, dict]:
        """Every mix for this person, by key, with its songs. Made once a day (they're daily
        mixes), again sooner if the library, your likes or what you've turned down change."""
        now = time.time()
        with db() as conn:
            lib = conn.execute("SELECT COUNT(*), MAX(id), SUM(sound IS NOT NULL) / 500 FROM tracks").fetchone()
            mine = conn.execute("SELECT (SELECT COUNT(*) FROM likes WHERE user_id = ?), (SELECT COUNT(*) FROM feedback WHERE user_id = ? AND kind != 'skip')",
                                (me_id, me_id)).fetchone()
        key = (me_id, mixes.day_seed(me_id, now), mixes.week_seed(me_id, now), tuple(lib), tuple(mine))
        got = _mix_cache.get(key)
        if got is None:
            got = _make_mixes(me_id, now)
            for k in [k for k in _mix_cache if k[0] == me_id]:
                del _mix_cache[k]
            if len(_mix_cache) > 100:
                _mix_cache.clear()
            _mix_cache[key] = got
        return got

    def _make_mixes(me_id: int, now: float) -> dict[str, dict]:
        with db() as conn:
            rows = conn.execute(TRACK_SELECT).fetchall()
            plays = [(r[0], r[1]) for r in conn.execute(
                "SELECT track_id, played_at FROM plays WHERE user_id = ? AND played_at > ?", (me_id, now - 400 * 86400))]
            liked = {r[0] for r in conn.execute("SELECT track_id FROM likes WHERE user_id = ?", (me_id,))}
        score = mixes.affinity(plays, liked, now)
        by_id = {r["id"]: r for r in rows}
        out: dict[str, dict] = {}
        for m in mixes.daily_mixes(rows, score, _recommend, mixes.day_seed(me_id, now)):
            tracks = mixes.finish_daily(m, track_json)
            out[m["key"]] = {"key": m["key"], "kind": "daily", "name": m["name"], "description": m["description"],
                             "color": m["color"], "tracks": tracks, "covers": _covers_of(tracks, m["artists"])}
        lists = [
            ("on-repeat", "On Repeat", "The songs you’ve played most this past month", "#1971c2",
             [track_json(t) for t in mixes.on_repeat(by_id, plays, now)]),
            ("rediscover", "Rediscover", "Songs you used to play a lot, and haven’t lately", "#9c36b5",
             [track_json(t) for t in mixes.rediscover(by_id, plays, now)]),
            ("discover", "Discover", "Songs on your shelf you’ve never played, picked for you. New every week", "#0c8599",
             mixes.discover(rows, plays, score, _recommend, mixes.week_seed(me_id, now))),
        ]
        for key, name, desc, color, tracks in lists:
            if len(tracks) >= 5:
                out[key] = {"key": key, "kind": "list", "name": name, "description": desc, "color": color,
                            "tracks": tracks, "covers": _covers_of(tracks)}
        # Moods (Workout, Chill...), once enough of the library is measured. New every day.
        for m in moods.mood_mixes(rows, sound.energy(rows), score, mixes.day_seed(me_id, now)):
            tracks = [track_json(by_id[i]) for i in m["ids"] if i in by_id]
            out[m["key"]] = {"key": m["key"], "kind": "list", "name": m["name"], "description": m["description"],
                             "color": m["color"], "tracks": tracks, "covers": _covers_of(tracks)}
        return out

    def _summary(m: dict) -> dict:
        return {k: v for k, v in m.items() if k != "tracks"} | {
            "trackCount": len(m["tracks"]), "duration": round(sum(t["duration"] for t in m["tracks"]))}

    @app.get("/api/mixes")
    def list_mixes():
        """Made for you: Shelf Mixes and the rest, without their songs."""
        return [_summary(m) for m in _made_for_you(uid()).values()]

    @app.get("/api/mixes/{key}")
    def get_mix(key: str):
        m = _made_for_you(uid()).get(key)
        if not m:
            raise HTTPException(404, "This mix isn’t around today")
        return _summary(m) | {"tracks": m["tracks"]}

    @app.get("/api/radio")
    def radio(track: int | None = None, artist: str | None = Query(None, max_length=200),
              limit: int = Query(50, ge=5, le=200)):
        """Song or artist radio: the seed, then songs from across the library that fit it.
        Different each time it's started."""
        rng = random.Random()
        with db() as conn:
            rows = conn.execute(TRACK_SELECT).fetchall()
        if track is not None:
            seed = next((r for r in rows if r["id"] == track), None)
            if not seed:
                raise HTTPException(404, "Track not found")
            same = [r for r in rows if mixes.artist_of(r).casefold() == mixes.artist_of(seed).casefold() and r["id"] != track]
            mine = [seed, *rng.sample(same, min(4, len(same)))]
            first = [track_json(seed)]
            name, desc = f"{seed['title']} Radio", f"Songs that go with {seed['title']} by {seed['artist']}"
            prefer = [mixes.artist_of(seed)]
        elif artist:
            # Their songs, shared ones and features included.
            mine = [r for r in rows if credits.credited(r["album_artist_name"], artist) or credits.credited(r["artist"], artist)]
            if not mine:
                raise HTTPException(404, "No music by this artist")
            first = []
            shown = credits.display(artist)
            name, desc = f"{shown} Radio", f"{shown} and artists like them"
            prefer = [shown]
        else:
            raise HTTPException(400, "Start radio from a song or an artist")
        mine_ids = {r["id"] for r in mine}
        pool = [r for r in rows if r["id"] not in mine_ids or track is None]
        picks = _recommend(mine, [r for r in pool if r["id"] != track], rng.randrange(1, 10**6), limit - len(first))
        # Artist radio leans on the artist: about a third of it is theirs.
        if artist:
            own = [track_json(r) for r in rng.sample(mine, min(len(mine), limit // 3))]
            have = {t["id"] for t in own}
            picks = own + [t for t in picks if t["id"] not in have][: limit - len(own)]
            rng.shuffle(picks)
        tracks = first + picks
        return {"key": "radio", "kind": "radio", "name": name, "description": desc, "color": "#364fc7",
                "tracks": tracks, "covers": _covers_of(tracks, prefer), "trackCount": len(tracks)}

    @app.patch("/api/playlists/{pid}")
    def edit_playlist(pid: int, body: PlaylistBody):
        with db() as conn:
            _require_playlist(conn, pid)
            if body.shared is not None:
                conn.execute("UPDATE playlists SET shared = ? WHERE id = ?", (body.shared, pid))
            if body.mix is not None:
                conn.execute("UPDATE playlists SET mix = ? WHERE id = ?", (int(body.mix), pid))
            if body.name is not None and body.name.strip():
                conn.execute("UPDATE playlists SET name = ? WHERE id = ?", (body.name.strip(), pid))
            if body.description is not None:
                conn.execute("UPDATE playlists SET description = ? WHERE id = ?", (body.description.strip(), pid))
            if body.rules is not None:
                row = conn.execute("SELECT rules FROM playlists WHERE id = ?", (pid,)).fetchone()
                if not row["rules"]:
                    raise HTTPException(400, "Only a smart playlist has rules")
                _set_rules(conn, pid, body.rules)
            _touch(conn, pid)
            return _playlist_summary(conn, pid)

    @app.delete("/api/playlists/{pid}")
    def delete_playlist(pid: int):
        with db() as conn:
            _require_playlist(conn, pid)
            conn.execute("DELETE FROM playlists WHERE id = ?", (pid,))
        return {"ok": True}

    @app.post("/api/playlists/{pid}/tracks")
    def add_to_playlist(pid: int, body: PlaylistAdd):
        with db() as conn:
            _require_playlist(conn, pid, "tracks")
            _not_smart(conn, pid)
            added = _append(conn, pid, body.trackIds, body.suggested)
            _touch(conn, pid)
            return {"added": added, **_playlist_summary(conn, pid)}

    @app.delete("/api/playlists/{pid}/tracks/{entry_id}")
    def remove_from_playlist(pid: int, entry_id: int):
        with db() as conn:
            _require_playlist(conn, pid, "tracks")
            entry = conn.execute("SELECT track_id, suggested FROM playlist_tracks WHERE id = ? AND playlist_id = ?",
                                 (entry_id, pid)).fetchone()
            if not entry:
                raise HTTPException(404, "That song isn’t in this playlist")
            conn.execute("DELETE FROM playlist_tracks WHERE id = ?", (entry_id,))
            if entry["suggested"]:  # a suggestion taken back out: suggestions learn from it
                conn.execute("INSERT INTO feedback(user_id, track_id, kind, playlist_id, at) VALUES(?, ?, 'removed', ?, ?)",
                             (uid(), entry["track_id"], pid, time.time()))
            _touch(conn, pid)
            return _playlist_summary(conn, pid)

    @app.put("/api/playlists/{pid}/tracks/{entry_id}/transition")
    def set_transition(pid: int, entry_id: int, body: TransitionBody):
        """How a song hands over to the next one when the playlist is played as a Mix."""
        with db() as conn:
            _require_playlist(conn, pid, "tracks")
            stored = body.stored()
            n = conn.execute("UPDATE playlist_tracks SET transition = ? WHERE id = ? AND playlist_id = ?",
                             (stored, entry_id, pid)).rowcount
            if not n:
                raise HTTPException(404, "That song isn’t in this playlist")
        return {"ok": True, "transition": transition_json(stored)}

    @app.get("/api/tracks/{track_id}/peaks")
    def track_peaks(track_id: int, start: float = Query(0, ge=0), end: float = Query(60, gt=0),
                    per_second: int = Query(20, ge=2, le=50)):
        """The waveform of part of a song (at most two minutes), for the transition editor."""
        with db() as conn:
            row = conn.execute("SELECT path FROM tracks WHERE id = ?", (track_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Track not found")
        end = min(end, start + 120)
        try:
            return peaks.peaks(Path(row["path"]), start, end, per_second)
        except (OSError, subprocess.SubprocessError) as e:
            raise HTTPException(500, f"Couldn’t read this song’s waveform: {e}") from e

    # ---------- liked songs ----------

    @app.get("/api/likes")
    def likes():
        with db() as conn:
            rows = conn.execute(
                f"""SELECT l.liked_at, q.* FROM likes l JOIN ({TRACK_SELECT}) q ON q.id = l.track_id
                    WHERE l.user_id = ? ORDER BY l.liked_at DESC""", (uid(),)).fetchall()
        return [{**track_json(r), "addedAt": r["liked_at"]} for r in rows]

    @app.get("/api/likes/ids")
    def liked_ids():
        with db() as conn:
            return [r[0] for r in conn.execute(
                "SELECT track_id FROM likes WHERE user_id = ? ORDER BY liked_at DESC", (uid(),))]

    @app.put("/api/likes/{track_id}")
    def like(track_id: int):
        if podcasts.is_episode(track_id):
            raise HTTPException(400, "Favourites are for songs. The podcast keeps your place in its episodes.")
        with db() as conn:
            if not conn.execute("SELECT 1 FROM tracks WHERE id = ?", (track_id,)).fetchone():
                raise HTTPException(404, "Track not found")
            conn.execute("INSERT OR IGNORE INTO likes(user_id, track_id, liked_at) VALUES(?, ?, ?)",
                         (uid(), track_id, time.time()))
        return {"liked": True}

    @app.delete("/api/likes/{track_id}")
    def unlike(track_id: int):
        with db() as conn:
            conn.execute("DELETE FROM likes WHERE user_id = ? AND track_id = ?", (uid(), track_id))
        return {"liked": False}

    @app.get("/api/tracks/recent")
    def recent_tracks(limit: int = Query(50, ge=1, le=200)):
        """Songs played lately, most recent first, each once."""
        with db() as conn:
            rows = conn.execute(
                f"""SELECT p.last, q.* FROM (SELECT track_id, MAX(played_at) AS last FROM plays
                    WHERE user_id = ? GROUP BY track_id) p
                    JOIN ({TRACK_SELECT}) q ON q.id = p.track_id ORDER BY p.last DESC LIMIT ?""",
                (uid(), limit)).fetchall()
        return [{**track_json(r), "playedAt": r["last"]} for r in rows]

    @app.put("/api/playlists/{pid}/order")
    def reorder_playlist(pid: int, body: PlaylistOrder):
        with db() as conn:
            _require_playlist(conn, pid, "tracks")
            _not_smart(conn, pid)
            current = {r["id"] for r in conn.execute("SELECT id FROM playlist_tracks WHERE playlist_id = ?", (pid,))}
            if set(body.entryIds) != current or len(body.entryIds) != len(current):
                raise HTTPException(409, "The playlist changed; reload it and try again")
            conn.executemany("UPDATE playlist_tracks SET position = ? WHERE id = ?",
                             [(i + 1, eid) for i, eid in enumerate(body.entryIds)])
            _touch(conn, pid)
        return {"ok": True}

    # ---------- devices ----------

    # ---------- party mode ----------

    parties: dict[int, party.Party] = {}

    def _party(host: int) -> party.Party:
        p = parties.get(host)
        if p is None:
            raise HTTPException(404, "That party has ended")
        return p

    def _party_queue(host: int):
        """(the host's queue as track dicts, the index playing), from their Connect session."""
        hub = hubs.get(host)
        if not hub or not hub.state or not hub.active or hub.active not in hub.devices:
            return None, 0
        return (hub.queue or {}).get("tracks") or [], int(hub.state.get("index") or 0)

    def _host_position(hub) -> float:
        if not hub or not hub.state:
            return 0.0
        s = hub.state
        pos = float(s.get("position") or 0)
        if s.get("playing"):
            pos += time.monotonic() - hub.state_at
            if s.get("duration"):
                pos = min(pos, max(0.0, float(s["duration"]) - 0.5))
        return round(pos, 2)

    @app.post("/api/party")
    def start_party():
        """Start a party: other people here can join your playing, add songs and vote to skip."""
        me_id = uid()
        p = parties.setdefault(me_id, party.Party(host=me_id, started=time.time()))
        return {"host": me_id, "started": p.started}

    @app.delete("/api/party")
    def end_party():
        if parties.pop(uid(), None) is None:
            raise HTTPException(404, "You’re not hosting a party")
        return {"ok": True}

    @app.get("/api/parties")
    def list_parties():
        """The parties going on, to join."""
        with db() as conn:
            names = {r["id"]: r["username"] for r in conn.execute("SELECT id, username FROM users")}
        now = time.time()
        me_id = uid()
        return [{"host": {"id": h, "username": names.get(h, "Someone")}, "people": len(p.present(now)),
                 "joined": me_id in p.members, "mine": h == me_id} for h, p in parties.items() if h in names]

    @app.post("/api/party/{host}/join")
    def join_party(host: int):
        _party(host).join(uid(), time.time())
        return {"ok": True}

    @app.post("/api/party/{host}/leave")
    def leave_party(host: int):
        _party(host).leave(uid())
        return {"ok": True}

    @app.get("/api/party/{host}")
    def party_status(host: int):
        """What's playing at the party, what's next, who's there and the skip votes."""
        p = _party(host)
        me_id, now = uid(), time.time()
        p.seen(me_id, now)
        queue, index = _party_queue(host)
        hub = hubs.get(host)
        with db() as conn:
            names = {r["id"]: r["username"] for r in conn.execute("SELECT id, username FROM users")}
        if queue is not None:
            p.prune([t.get("id") for t in queue], index)
        current = queue[index] if queue and 0 <= index < len(queue) else None
        if current and current.get("id") != p.vote_track:
            p.vote_track, p.votes = current.get("id"), set()
        return {
            "host": {"id": host, "username": names.get(host, "Someone")}, "isHost": me_id == host,
            "joined": me_id == host or me_id in p.members,
            "members": [names.get(u, "Someone") for u in [host, *sorted(p.members)] if u in p.present(now)],
            "nowPlaying": current, "playing": bool(hub and hub.state and hub.state.get("playing")),
            # Where the host is in the song right now, so guests' devices can play along in step.
            "position": _host_position(hub),
            "upNext": (queue or [])[index + 1: index + 11],
            "votes": len(p.votes), "needed": p.needed(now), "youVoted": me_id in p.votes,
        }

    @app.post("/api/party/{host}/add")
    async def party_add(host: int, body: PlaylistAdd):
        """Songs to play at the party: after the one playing, behind those added before them."""
        p = _party(host)
        me_id = uid()
        if me_id != host and me_id not in p.members:
            raise HTTPException(403, "Join the party first")
        queue, index = _party_queue(host)
        if queue is None:
            raise HTTPException(409, "Nothing’s playing at this party right now")
        with db() as conn:
            marks = ",".join("?" * len(body.trackIds)) or "NULL"
            rows = {r["id"]: r for r in conn.execute(f"{TRACK_SELECT} WHERE t.id IN ({marks})", body.trackIds)}
        tracks = [track_json(rows[i]) for i in body.trackIds if i in rows]
        if not tracks:
            raise HTTPException(404, "Those songs aren’t on the shelf")
        ids = [t.get("id") for t in queue]
        p.prune(ids, index)
        at = party.insert_at(ids, index, p.pending)
        if not await hubs[host].command("insertAt", at, tracks):
            raise HTTPException(409, "Nothing’s playing at this party right now")
        p.pending += [t["id"] for t in tracks]
        p.seen(me_id, time.time())
        return {"added": len(tracks), "at": at}

    @app.post("/api/party/{host}/skip")
    async def party_skip(host: int):
        """A vote to skip the song that's playing."""
        p = _party(host)
        me_id, now = uid(), time.time()
        if me_id != host and me_id not in p.members:
            raise HTTPException(403, "Join the party first")
        p.seen(me_id, now)
        queue, index = _party_queue(host)
        if not queue:
            raise HTTPException(409, "Nothing’s playing at this party right now")
        if p.vote(me_id, queue[index].get("id"), now):
            await hubs[host].command("next")
            return {"skipped": True, "votes": 0, "needed": p.needed(now)}
        return {"skipped": False, "votes": len(p.votes), "needed": p.needed(now)}

    @app.websocket("/api/connect")
    async def connect_ws(ws: WebSocket):
        # The HTTP sign-in check doesn't cover WebSockets, so it's repeated here.
        user = auth.user_for(token_from(ws.headers, ws.cookies) or ws.query_params.get("token"))
        if user is None or not same_origin(ws):
            await ws.close(code=1008)
            return
        hub = hubs.get(user.id)
        if hub is None:
            hub = hubs[user.id] = Hub(on_change=lambda event, track, device, u=user.id: hooks.emit(
                event, {"track": webhooks.track_json(track), "device": device}, u))
        await hub.serve(ws)

    @app.get("/api/tracks/{track_id}/similar")
    def similar(track_id: int, limit: int = Query(40, ge=1, le=200)):
        """Autoplay: more songs by the same artist or in the same genre, from other albums first."""
        if podcasts.is_episode(track_id):
            return []  # after an episode, nothing plays by itself
        with db() as conn:
            seed = conn.execute(f"{TRACK_SELECT} WHERE t.id = ?", (track_id,)).fetchone()
            if not seed:
                raise HTTPException(404, "Track not found")
            rows = conn.execute(
                f"""{TRACK_SELECT}
                WHERE t.id != ? AND (a.artist = ? COLLATE NOCASE OR (t.genre IS NOT NULL AND t.genre = ? COLLATE NOCASE))
                ORDER BY (t.album_key = ?), RANDOM() LIMIT ?""",
                (track_id, seed["album_artist_name"], seed["genre"], seed["album_key"], limit),
            ).fetchall()
            if len(rows) < limit:  # small library or untagged genre: top up with anything
                seen = [track_id, *[r["id"] for r in rows]]
                marks = ",".join("?" * len(seen))
                rows += conn.execute(
                    f"{TRACK_SELECT} WHERE t.id NOT IN ({marks}) ORDER BY RANDOM() LIMIT ?",
                    (*seen, limit - len(rows)),
                ).fetchall()
        return [track_json(r) for r in rows]

    @app.delete("/api/history")
    def clear_history():
        with db() as conn:
            n = conn.execute("DELETE FROM plays WHERE user_id = ?", (uid(),)).rowcount
        return {"removed": n}

    @app.get("/api/storage")
    def storage():
        cover_bytes = sum(p.stat().st_size for p in cfg.cover_dir.glob("*.webp"))
        return {"transcodeBytes": transcode.cache_size(cfg.transcode_dir), "coverBytes": cover_bytes,
                "transcodeLimitBytes": cfg.transcode_cache_mb * 1024 * 1024}

    @app.post("/api/storage/clear")
    def clear_storage():
        admin_only()
        return {"freedBytes": transcode.clear_cache(cfg.transcode_dir)}

    # ---------- web app ----------

    # ---------- share links ----------

    def _share_tracks(conn, row) -> list:
        kind, item = row["kind"], row["item_id"]
        if kind == "track":
            return conn.execute(f"{TRACK_SELECT} WHERE t.id = ?", (item,)).fetchall()
        if kind == "album":
            return conn.execute(f"{TRACK_SELECT} WHERE a.id = ? {TRACK_ORDER}", (item,)).fetchall()
        p = conn.execute("SELECT * FROM playlists WHERE id = ?", (item,)).fetchone()
        if not p:
            return []
        rules = _rules_of(p)
        if rules:
            return _smart_rows(conn, item, rules, row["user_id"])
        return conn.execute(f"""SELECT q.* FROM playlist_tracks e JOIN ({TRACK_SELECT}) q ON q.id = e.track_id
                                WHERE e.playlist_id = ? ORDER BY e.position""", (item,)).fetchall()

    def _share_heading(conn, row) -> tuple[str, str]:
        """What a link shows as its title, and by whom."""
        kind, item = row["kind"], row["item_id"]
        if kind == "track":
            t = conn.execute("SELECT title, artist FROM tracks WHERE id = ?", (item,)).fetchone()
            return (t["title"], t["artist"]) if t else ("A song", "")
        if kind == "album":
            a = conn.execute("SELECT title, artist FROM albums WHERE id = ?", (item,)).fetchone()
            return (a["title"], a["artist"]) if a else ("An album", "")
        p = conn.execute("SELECT name FROM playlists WHERE id = ?", (item,)).fetchone()
        return (p["name"] if p else "A playlist", f"A playlist by {row['username']}")

    def _share_json(conn, row) -> dict:
        title, by = _share_heading(conn, row)
        return {"token": row["token"], "path": f"/s/{row['token']}", "kind": row["kind"], "id": row["item_id"],
                "title": title, "by": by, "createdAt": row["created_at"], "expiresAt": row["expires_at"],
                "expired": shares.expired(row), "opened": row["opened"], "sharedBy": row["username"]}

    @app.post("/api/shares")
    def create_share(body: ShareBody):
        user = CURRENT.get()
        with db() as conn:
            if not shares.enabled(conn):
                raise HTTPException(403, "Share links are off on this server. Its admin can turn them on.")
            if body.kind == "track":
                found = conn.execute("SELECT 1 FROM tracks WHERE id = ?", (body.id,)).fetchone()
            elif body.kind == "album":
                found = conn.execute("SELECT 1 FROM albums WHERE id = ?", (body.id,)).fetchone()
            else:
                _require_playlist(conn, body.id, "read")
                found = True
            if not found:
                raise HTTPException(404, "Not found")
            token = shares.create(conn, user.id, body.kind, body.id, body.days)
            return _share_json(conn, shares.find(conn, token))

    @app.get("/api/shares")
    def my_shares():
        with db() as conn:
            return [_share_json(conn, r) for r in shares.listed(conn, uid())]

    @app.delete("/api/shares/{token}")
    def stop_share(token: str):
        user = CURRENT.get()
        with db() as conn:
            row = shares.find(conn, token)
            if not row or (row["user_id"] != user.id and not user.admin):
                raise HTTPException(404, "No such link")
            shares.stop(conn, token)
        return {"ok": True}

    @app.get("/api/admin/shares")
    def admin_shares():
        admin_only()
        with db() as conn:
            return {"enabled": shares.enabled(conn), "links": [_share_json(conn, r) for r in shares.listed(conn)]}

    @app.patch("/api/admin/shares")
    def set_sharing(body: SharingBody):
        admin_only()
        with db() as conn:
            shares.set_enabled(conn, body.enabled)
        return admin_shares()

    def _request_json(row, me: int) -> dict:
        return {"id": row["id"], "artist": row["artist"], "album": row["album"], "note": row["note"],
                "status": row["status"], "requestedBy": row["username"], "mine": row["user_id"] == me,
                "createdAt": row["created_at"], "resolvedAt": row["resolved_at"],
                "artistId": row["artist_mbid"], "albumId": row["album_mbid"], "year": row["year"], "type": row["kind"]}

    @app.get("/api/requests")
    def list_requests():
        me = uid()
        with db() as conn:
            return {"requests": [_request_json(r, me) for r in wishlist.listed(conn)],
                    "lookup": cfg.artist_info}

    @app.get("/api/requests/lookup")
    async def lookup_for_request(kind: Literal["artist", "album"], q: str = Query("", max_length=200),
                                 artist: str = Query("", max_length=300),
                                 artistId: str | None = Query(None, pattern=MBID_PATTERN)):
        """What MusicBrainz knows that matches what's being typed: artists, or albums (all of a
        picked artist's, narrowed by what's typed). Each says whether it's on the shelf already."""
        if not cfg.artist_info:
            return {"results": [], "off": True}
        q = q.strip()
        try:
            if kind == "artist":
                found = await asyncio.to_thread(wishlist.find_artists, q) if len(q) >= 2 else []
            elif artistId:
                found = await asyncio.to_thread(wishlist.artist_albums, artistId)
                want = videos.fold(q)
                found = [a for a in found if want in videos.fold(a["title"])] if want else found
            else:
                found = await asyncio.to_thread(wishlist.find_albums, q, artist) if len(q) >= 2 else []
        except (OSError, ValueError) as e:  # URLError is an OSError
            log.warning("MusicBrainz lookup failed: %s", e)
            return {"results": [], "error": "MusicBrainz didn’t answer. You can still type it in yourself."}
        with db() as conn:
            shelf = wishlist.Shelf(conn)
            for x in found:
                x["onShelf"] = shelf.has(x["name"], None) if kind == "artist" else shelf.has(x.get("artist") or artist, x["title"])
        return {"results": found[:60]}

    @app.post("/api/requests")
    def create_request(body: RequestBody):
        user = CURRENT.get()
        artist = body.artist.strip()
        album = (body.album or "").strip() or None
        if not artist:
            raise HTTPException(400, "Whose music is it? The artist's name is the one thing a request needs.")
        with db() as conn:
            if wishlist.on_shelf(conn, artist, album):
                raise HTTPException(409, "Good news: that’s already on the shelf.")
            earlier = wishlist.open_duplicate(conn, artist, album, body.albumId if album else None)
            if earlier is not None:
                who = "You" if earlier["user_id"] == user.id else earlier["username"]
                raise HTTPException(409, f"{who} already asked for this. An admin will get to it.")
            rid = wishlist.create(conn, user.id, artist, album, (body.note or "").strip(), artist_id=body.artistId,
                                  album_id=body.albumId if album else None, year=body.year if album else None,
                                  kind=(body.type or "").strip() or None if album else None)
            return _request_json(wishlist.find(conn, rid), user.id)

    @app.patch("/api/requests/{rid}")
    def resolve_request(rid: int, body: RequestStatusBody):
        admin_only()
        with db() as conn:
            if wishlist.find(conn, rid) is None:
                raise HTTPException(404, "No such request")
            wishlist.set_status(conn, rid, body.status)
            return _request_json(wishlist.find(conn, rid), uid())

    @app.delete("/api/requests/{rid}")
    def withdraw_request(rid: int):
        user = CURRENT.get()
        with db() as conn:
            row = wishlist.find(conn, rid)
            if row is None or (row["user_id"] != user.id and not user.admin):
                raise HTTPException(404, "No such request")
            wishlist.remove(conn, rid)
        return {"ok": True}

    def _secure_json(request: Request) -> dict:
        return {"url": app.state.secure_url, "here": request.url.scheme == "https",
                "tailscale": secure.tailscale_state(cfg.port)}

    def _save_secure(url: str | None) -> None:
        with db() as conn:
            secure.set_url(conn, url)
        app.state.secure_url = url

    @app.get("/api/admin/secure")
    def admin_secure(request: Request):
        admin_only()
        return _secure_json(request)

    @app.put("/api/admin/secure")
    def set_secure(body: SecureBody, request: Request):
        admin_only()
        url = None
        if body.url:
            url = secure.normalize(body.url)
            if url is None:
                raise HTTPException(400, "That isn’t an https address. It should look like https://music.example.org.")
            if not secure.reaches(url):
                raise HTTPException(400, f"Shelf couldn’t reach itself at {url}. Check the address leads to this server.")
        _save_secure(url)
        return _secure_json(request)

    @app.post("/api/admin/secure/tailscale")
    def set_funnel(body: FunnelBody, request: Request):
        admin_only()
        exe = secure.tailscale_exe()
        if exe is None:
            raise HTTPException(400, "Tailscale isn’t installed on the server’s computer.")
        if body.on:
            got = secure.start_funnel(exe, cfg.port)
            if got.get("allow"):
                return _secure_json(request) | {"allow": got["allow"]}
            if not got["ok"]:
                raise HTTPException(400, f"Tailscale said: {got['error']}")
            _save_secure(got["url"])
        else:
            got = secure.stop_funnel(exe)
            if not got["ok"]:
                raise HTTPException(400, f"Tailscale said: {got['error']}")
            if (app.state.secure_url or "").endswith(".ts.net"):
                _save_secure(None)
        return _secure_json(request)

    def _open_share(conn, token: str):
        """A link that works now, or the reason it doesn't (open to anyone: no account needed)."""
        row = shares.find(conn, token)
        if not row or not shares.enabled(conn):
            raise HTTPException(404, "This link doesn’t work. It may have been stopped.")
        if shares.expired(row):
            raise HTTPException(410, "This link has expired.")
        return row

    @app.get("/s/{token}")
    def share_page(token: str):
        return FileResponse(WEB_DIR / "share.html", media_type="text/html", headers={"Cache-Control": "no-cache"})

    @app.get("/s/{token}/info")
    def share_info(token: str):
        with db() as conn:
            row = _open_share(conn, token)
            title, by = _share_heading(conn, row)
            rows = _share_tracks(conn, row)
            shares.opened(conn, token)
        tracks = [{"id": r["id"], "title": r["title"], "artist": r["artist"], "album": r["album_title"],
                   "albumId": r["album_id"], "duration": round(r["duration"] or 0, 1),
                   "cover": _cover_version(r["cover_src"])} for r in rows]
        cover = next((t for t in tracks if t["cover"]), None)
        return {"kind": row["kind"], "title": title, "by": by, "sharedBy": row["username"],
                "expiresAt": row["expires_at"], "tracks": tracks,
                "cover": f"/s/{token}/albums/{cover['albumId']}/cover?v={cover['cover']}" if cover else None}

    def _share_has(conn, row, track_id: int | None = None, album_id: int | None = None) -> bool:
        return any((track_id is not None and r["id"] == track_id) or (album_id is not None and r["album_id"] == album_id)
                   for r in _share_tracks(conn, row))

    @app.get("/s/{token}/tracks/{track_id}/stream")
    async def share_stream(request: Request, token: str, track_id: int, q: str = "original"):
        with db() as conn:
            row = _open_share(conn, token)
            if not _share_has(conn, row, track_id=track_id):
                raise HTTPException(404, "Not in this link")
        return await stream(request, track_id, q)

    @app.get("/s/{token}/albums/{album_id}/cover")
    def share_cover(token: str, album_id: int, size: int = Query(640, ge=32, le=1200)):
        with db() as conn:
            row = _open_share(conn, token)
            if not _share_has(conn, row, album_id=album_id):
                raise HTTPException(404, "Not in this link")
        return album_cover(album_id, size)

    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app
