"""HTTP API and static web app."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import re
import subprocess
import urllib.parse
import logging
import threading
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request, Response, WebSocket
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import procs
from . import analysis, covers, credits, genres, updates, dj, folders, local_llm, loudness, lyrics, mixes, moods, peaks, playlist_maker, releases, ripper, scrobble, sound, together, transcode, uploads, videos
from . import artists as artist_info
from .connect import Hub, same_origin
from . import __version__
from .auth import COOKIE, MAX_AGE, Auth, User, check_username, token_from
from .config import Config
from .db import get_meta, init_db, session
from .scanner import scan, warm_covers

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
            }
            self.state["running"] = False
            # Measure loudness for volume normalization (slow, so it runs after the scan is done).
            self.state["measuring"] = True
            loudness.analyze_pending(self.cfg.db_path, stop=self._stop)
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
OPEN_PATHS = {"/api/session", "/api/login", "/api/setup", "/api/ping"}


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
    new_version = updates.Updates(enabled=cfg.check_updates)
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
            new_releases.start()
            new_version.start()
        yield
        new_version.stop()
        scanner.stop()
        scrobbler.stop()
        new_releases.stop()
        dj_voice.stop()
        natural.stop()
        llm.stop()

    app = FastAPI(title="Shelf", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.scanner = scanner
    app.state.cfg = cfg
    hubs: dict[int, Hub] = {}  # Connect: each person's devices only see each other
    app.state.hubs = hubs

    def db():
        return session(cfg.db_path)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
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

    def _me_json(user: User) -> dict:
        with db() as conn:
            r = conn.execute("SELECT share_activity, listenbrainz_user, listenbrainz_token FROM users WHERE id = ?",
                             (user.id,)).fetchone()
        return user.json() | {"shareActivity": bool(r["share_activity"]) if r else True,
                              "listenbrainz": (r["listenbrainz_user"] or "ListenBrainz") if r and r["listenbrainz_token"] else None}

    @app.get("/api/session")
    def get_session(request: Request):
        user = auth.user_for(token_from(request.headers, request.cookies))
        return {"setup": not auth.has_users(), "signedIn": user is not None,
                "user": _me_json(user) if user else None, "version": __version__,
                "features": {"dj": _dj_on() if user else False}}

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
                    conn.execute("DELETE FROM scrobbles WHERE user_id = ?", (user.id,))
        return _me_json(user)

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
        with db() as conn:
            conn.execute("DELETE FROM likes WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM plays WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM playlists WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        auth.forget(user_id)
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
        }

    @app.post("/api/admin/update/check")
    def update_check():
        """Look for a newer Shelf now (it also looks every six hours)."""
        admin_only()
        return new_version.check()

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
        return [
            {"name": a["name"], "albums": a["albums"], "tracks": a["tracks"],
             "coverAlbumId": a["cover"][1] if a["cover"] else None,
             "cover": _cover_version(a["cover"][2]) if a["cover"] else None}
            for a in sorted(_album_artists(rows), key=lambda a: a["name"].casefold())
        ]

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
        return {
            "artists": [{"name": a["name"], "albums": a["albums"]} for a in artist_rows],
            "albums": [album_json(r) for r in album_rows],
            "tracks": [track_json(r) for r in track_rows],
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
                SELECT * FROM albums a WHERE NOT EXISTS (
                    SELECT 1 FROM plays p WHERE p.album_key = a.key AND p.played_at > ? AND p.user_id = ?
                ) ORDER BY RANDOM() LIMIT 14
                """,
                (now - 30 * 86400, me_id),
            ).fetchall()
            listened = conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(t.duration), 0) AS secs FROM plays p "
                "JOIN tracks t ON t.id = p.track_id WHERE p.played_at > ? AND p.user_id = ?",
                (now - 7 * 86400, me_id),
            ).fetchone()
        return {
            "recent": [album_json(r) | {"lastPlayed": r["last_played"]} for r in recent],
            "top": [album_json(r) | {"plays": r["plays"]} for r in top],
            "added": [album_json(r) for r in added],
            "rediscover": [album_json(r) for r in rediscover],
            "week": {"plays": listened["n"], "seconds": round(listened["secs"])},
        }

    @app.post("/api/tracks/{track_id}/played")
    def played(track_id: int, at: float | None = Query(None)):
        """A listen. `at`: when, for listens made offline and sent later (up to 60 days back)."""
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
    async def stream(track_id: int, q: str = "original"):
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
        with db() as conn:
            row = conn.execute(
                "SELECT path, title, artist, album, duration FROM tracks WHERE id = ?", (track_id,)
            ).fetchone()
        if not row:
            raise HTTPException(404, "Track not found")
        result = lyrics.lyrics_for(cfg.db_path, row, cfg.online_lyrics)
        response.headers["Cache-Control"] = "private, max-age=600"
        return result

    # ---------- music videos ----------

    @app.get("/api/tracks/{track_id}/video")
    def track_video(track_id: int, response: Response):
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
        return {
            "name": display,
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
            "trackCount": p["n"], "duration": round(p["dur"], 1),
            "covers": [{"albumId": r["id"], "cover": _cover_version(r["cover_src"])} for r in covers_rows],
            "createdAt": p["created_at"], "updatedAt": p["updated_at"], "mix": bool(p["mix"]),
            "shared": p["shared"], "mine": p["user_id"] == uid(), "canEdit": p["user_id"] == uid() or p["shared"] == 2,
            "owner": {"id": p["user_id"], "username": p["owner_name"] or "Someone"},
            "following": bool(p["following"]), "followers": p["followers"],
        }

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

    def _append(conn, pid: int, track_ids: list[int]) -> int:
        known = {r["id"] for r in conn.execute(
            f"SELECT id FROM tracks WHERE id IN ({','.join('?' * len(track_ids))})", track_ids)} if track_ids else set()
        start = conn.execute("SELECT COALESCE(MAX(position), 0) FROM playlist_tracks WHERE playlist_id = ?", (pid,)).fetchone()[0]
        now = time.time()
        me_id = uid()
        rows = [(pid, tid, start + i + 1, now, me_id) for i, tid in enumerate(t for t in track_ids if t in known)]
        conn.executemany("INSERT INTO playlist_tracks(playlist_id, track_id, position, added_at, added_by) VALUES(?, ?, ?, ?, ?)", rows)
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
            _append(conn, pid, body.trackIds)
            return _playlist_summary(conn, pid)

    @app.get("/api/playlists/{pid}")
    def get_playlist(pid: int):
        with db() as conn:
            _require_playlist(conn, pid, "read")
            summary = _playlist_summary(conn, pid)
            if not summary:
                raise HTTPException(404, "Playlist not found")
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
            mine = conn.execute(
                f"""SELECT q.* FROM playlist_tracks e JOIN ({TRACK_SELECT}) q ON q.id = e.track_id
                    WHERE e.playlist_id = ?""", (pid,)).fetchall()
            if not mine:
                return []
            pool = conn.execute(
                f"""{TRACK_SELECT} WHERE t.id NOT IN (SELECT track_id FROM playlist_tracks WHERE playlist_id = ?)""",
                (pid,)).fetchall()
        return _recommend(mine, pool, seed, limit)

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

    def _recommend(mine, pool, seed: int, limit: int) -> list[dict]:
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
        rng = random.Random(seed)
        scored = []
        for t in pool:
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

    def _made_for_you(me_id: int) -> dict[str, dict]:
        """Every mix for this person, by key, with its songs."""
        now = time.time()
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
            added = _append(conn, pid, body.trackIds)
            _touch(conn, pid)
            return {"added": added, **_playlist_summary(conn, pid)}

    @app.delete("/api/playlists/{pid}/tracks/{entry_id}")
    def remove_from_playlist(pid: int, entry_id: int):
        with db() as conn:
            _require_playlist(conn, pid, "tracks")
            gone = conn.execute("DELETE FROM playlist_tracks WHERE id = ? AND playlist_id = ?", (entry_id, pid)).rowcount
            if not gone:
                raise HTTPException(404, "That song isn’t in this playlist")
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
            current = {r["id"] for r in conn.execute("SELECT id FROM playlist_tracks WHERE playlist_id = ?", (pid,))}
            if set(body.entryIds) != current or len(body.entryIds) != len(current):
                raise HTTPException(409, "The playlist changed; reload it and try again")
            conn.executemany("UPDATE playlist_tracks SET position = ? WHERE id = ?",
                             [(i + 1, eid) for i, eid in enumerate(body.entryIds)])
            _touch(conn, pid)
        return {"ok": True}

    # ---------- devices ----------

    @app.websocket("/api/connect")
    async def connect_ws(ws: WebSocket):
        # The HTTP sign-in check doesn't cover WebSockets, so it's repeated here.
        user = auth.user_for(token_from(ws.headers, ws.cookies) or ws.query_params.get("token"))
        if user is None or not same_origin(ws):
            await ws.close(code=1008)
            return
        hub = hubs.get(user.id)
        if hub is None:
            hub = hubs[user.id] = Hub()
        await hub.serve(ws)

    @app.get("/api/tracks/{track_id}/similar")
    def similar(track_id: int, limit: int = Query(40, ge=1, le=200)):
        """Autoplay: more songs by the same artist or in the same genre, from other albums first."""
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

    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app
