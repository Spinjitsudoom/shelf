"""The rest of the Subsonic API, and the OpenSubsonic extensions: podcasts, shares, accounts,
internet radio, chat, avatars, API keys, the play queue by position, playback reports, songs
that sound alike, and conversions apps choose for themselves (getTranscodeDecision).

Mixed into subsonic.Subsonic; the helpers it uses (self.song, self.db, Fail...) live there.
"""

from __future__ import annotations

import asyncio
import colorsys
import hashlib
import io
import json
import math
import secrets
import threading
import time
from contextvars import ContextVar
from pathlib import Path

from fastapi.responses import Response, StreamingResponse

from . import covers, credits, podcasts, shares, sound, transcode, videos
from .auth import check_password_rules
from .db import get_meta, set_meta

BASE_URL: ContextVar[str] = ContextVar("subsonic_base_url", default="")
STATES = ("starting", "playing", "paused", "stopped")
CHAT_KEEP = 1000
EXTENSIONS = [
    ("formPost", 1), ("songLyrics", 1), ("apiKeyAuthentication", 1), ("indexBasedQueue", 1), ("playbackReport", 1),
    ("sonicSimilarity", 1), ("transcodeOffset", 1), ("transcoding", 1), ("getPodcastEpisode", 1),
    ("topSongsByArtistId", 1),
]
# What a file's suffix and Shelf's codec name are called in transcoding profiles.
CONTAINERS = {"m4a": "mp4", "mp4": "mp4", "m4b": "mp4", "alac": "mp4", "aac": "aac", "mp3": "mp3", "flac": "flac",
              "ogg": "ogg", "oga": "ogg", "opus": "ogg", "wav": "wav", "aif": "aiff", "aiff": "aiff", "wma": "asf",
              "ape": "ape", "wv": "wv"}
CODECS = {"pcm": "pcm", "wavpack": "wv", "vorbis": "vorbis"}


def _dec(pw: str) -> str:
    if pw.startswith("enc:"):
        try:
            return bytes.fromhex(pw[4:]).decode()
        except (ValueError, UnicodeDecodeError):
            return ""
    return pw


def key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def new_api_key(conn, user_id: int, name: str) -> str:
    key = "shelf_" + secrets.token_urlsafe(30)
    conn.execute("INSERT INTO api_keys(user_id, name, key_hash, hint, created_at) VALUES(?, ?, ?, ?, ?)",
                 (user_id, (name or "App").strip()[:80] or "App", key_hash(key), key[-4:], time.time()))
    return key


def avatar_png(name: str, size: int = 256) -> bytes:
    """A round-cornered square in a colour of the name's own, with its first letter."""
    from PIL import Image, ImageDraw, ImageFont

    h = int(hashlib.md5(name.casefold().encode()).hexdigest()[:4], 16) / 0xFFFF
    r, g, b = (int(c * 255) for c in colorsys.hls_to_rgb(h, 0.42, 0.55))
    img = Image.new("RGB", (size, size), (r, g, b))
    draw = ImageDraw.Draw(img)
    letter = (name.strip()[:1] or "?").upper()
    try:
        font = ImageFont.load_default(size=int(size * 0.55))
    except TypeError:
        font = ImageFont.load_default()
    box = draw.textbbox((0, 0), letter, font=font)
    draw.text(((size - (box[2] - box[0])) / 2 - box[0], (size - (box[3] - box[1])) / 2 - box[1]), letter,
              fill=(255, 255, 255), font=font)
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


class More:
    """Mixed into subsonic.Subsonic."""

    _listening: dict[int, dict]
    _artist_sound: dict

    def _more_init(self) -> None:
        self._listening = {}  # what each person is hearing, from playback reports
        self._artist_sound = {"key": None, "vecs": {}}
        self.proxy_user = None  # set by the app: who a trusted reverse proxy says is asking

    # ----- signing in with an API key -----

    def key_user(self, p, client: str):
        from .subsonic import Fail

        if any(p.get(k) is not None for k in ("u", "t", "s", "p")):
            raise Fail(43, "Multiple conflicting authentication mechanisms provided")
        if self.auth.locked_out(client):
            raise Fail(40, "Too many wrong passwords: try again in 15 minutes")
        with self.db() as conn:
            row = conn.execute("SELECT id, user_id FROM api_keys WHERE key_hash = ?", (key_hash(p.get("apiKey")),)).fetchone()
            if row:
                conn.execute("UPDATE api_keys SET used_at = ? WHERE id = ?", (time.time(), row["id"]))
        user = self.auth.get(row["user_id"]) if row else None
        if user is None:
            self.auth.failed(client)
            raise Fail(44, "Invalid API key")
        return user

    def m_tokenInfo(self, p, user):
        return {"tokenInfo": {"username": user.username}}

    # ----- accounts -----

    def _admin(self, user, what: str):
        from .subsonic import Fail

        if not user.admin:
            raise Fail(50, f"Only an admin can {what}")

    def _named(self, name: str):
        from .subsonic import not_found

        row = self.auth.find(name)
        if not row:
            raise not_found("No such person")
        return row

    def m_createUser(self, p, user):
        from .subsonic import Fail

        self._admin(user, "add people")
        try:
            self.auth.create(p.need("username"), _dec(p.need("password")), admin=p.flag("adminRole", False))
        except ValueError as e:
            raise Fail(0, str(e))
        return {}

    def m_updateUser(self, p, user):
        from .subsonic import Fail

        self._admin(user, "change other people’s accounts")
        row = self._named(p.need("username"))
        try:
            if p.get("adminRole") is not None:
                admin = p.flag("adminRole", False)
                if not admin and row["is_admin"] and self.auth.admins() <= 1:
                    raise ValueError("Shelf needs at least one admin")
                with self.db() as conn:
                    conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (int(admin), row["id"]))
            if p.get("password"):
                self.auth.set_password(row["id"], _dec(p.get("password")))
        except ValueError as e:
            raise Fail(0, str(e))
        self.auth.forget(row["id"])
        return {}

    def m_deleteUser(self, p, user):
        from .subsonic import Fail

        self._admin(user, "remove people")
        row = self._named(p.need("username"))
        if row["id"] == user.id:
            raise Fail(0, "You can’t remove your own account")
        if row["is_admin"] and self.auth.admins() <= 1:
            raise Fail(0, "Shelf needs at least one admin")
        if self.remove_user:
            self.remove_user(row["id"])
        return {}

    def m_changePassword(self, p, user):
        from .subsonic import Fail

        row = self._named(p.need("username"))
        if row["id"] != user.id:
            self._admin(user, "change other people’s passwords")
        try:
            pw = _dec(p.need("password"))
            check_password_rules(pw)
            self.auth.set_password(row["id"], pw)
        except ValueError as e:
            raise Fail(0, str(e))
        return {}

    def m_getAvatar(self, p, user):  # answered with the image, see subsonic.mount
        row = self._named(p.get("username") or user.username)
        return Response(avatar_png(row["username"]), media_type="image/png",
                        headers={"Cache-Control": "private, max-age=86400"})

    # ----- shares -----

    def _share_rows(self, conn, row) -> list:
        from .subsonic import ORDER, TRACKS

        kind, item = row["kind"], row["item_id"]
        if kind == "track":
            return conn.execute(f"{TRACKS} WHERE t.id = ?", (item,)).fetchall()
        if kind == "album":
            return conn.execute(f"{TRACKS} WHERE a.id = ? {ORDER}", (item,)).fetchall()
        pl = conn.execute("SELECT * FROM playlists WHERE id = ?", (item,)).fetchone()
        if not pl:
            return []
        owner = self.auth.get(pl["user_id"])
        return self._playlist_tracks(conn, pl, owner) if owner else []

    def _share(self, conn, row, ctx) -> dict:
        from .subsonic import iso

        return {"id": row["token"], "url": f"{BASE_URL.get()}/s/{row['token']}", "description": row["description"] or "",
                "username": row["username"], "created": iso(row["created_at"]), "expires": iso(row["expires_at"]),
                "visitCount": row["opened"], "entry": [self.song(t, ctx) for t in self._share_rows(conn, row)]}

    def m_getShares(self, p, user):
        with self.db() as conn:
            ctx = self._ctx(conn, user.id)
            rows = [r for r in shares.listed(conn, user.id) if not shares.expired(r)]
            return {"shares": {"share": [self._share(conn, r, ctx) for r in rows]}}

    def _sharing_on(self, conn):
        from .subsonic import Fail

        if not shares.enabled(conn):
            raise Fail(50, "Share links are off on this server. Its admin can turn them on.")

    @staticmethod
    def _expires(p) -> float | None:
        ms = p.int("expires", 0, 0, 10**14)
        return ms / 1000 if ms else None

    def m_createShare(self, p, user):
        from .subsonic import album_num, not_found

        ids = p.all("id")
        if not ids:
            from .subsonic import missing
            raise missing("id")
        sid = ids[0]
        with self.db() as conn:
            self._sharing_on(conn)
            if sid.startswith("al-"):
                kind, item = "album", self._album_row(conn, sid)["id"]
            elif sid.isdigit() and conn.execute("SELECT 1 FROM tracks WHERE id = ?", (int(sid),)).fetchone():
                kind, item = "track", int(sid)
            elif sid.isdigit():
                kind, item = "playlist", self._playlist_row(conn, sid, user)["id"]
            else:
                raise not_found("Nothing to share by that id")
            token = shares.create(conn, user.id, kind, item, None)
            conn.execute("UPDATE shares SET description = ?, expires_at = ? WHERE token = ?",
                         ((p.get("description") or "")[:500] or None, self._expires(p), token))
            ctx = self._ctx(conn, user.id)
            return {"shares": {"share": [self._share(conn, shares.find(conn, token), ctx)]}}

    def _my_share(self, conn, token: str, user):
        from .subsonic import not_found

        row = shares.find(conn, token)
        if not row or (row["user_id"] != user.id and not user.admin):
            raise not_found("No such share")
        return row

    def m_updateShare(self, p, user):
        with self.db() as conn:
            row = self._my_share(conn, p.need("id"), user)
            if p.get("description") is not None:
                conn.execute("UPDATE shares SET description = ? WHERE token = ?", (p.get("description")[:500] or None, row["token"]))
            if p.get("expires") is not None:
                conn.execute("UPDATE shares SET expires_at = ? WHERE token = ?", (self._expires(p), row["token"]))
        return {}

    def m_deleteShare(self, p, user):
        with self.db() as conn:
            shares.stop(conn, self._my_share(conn, p.need("id"), user)["token"])
        return {}

    # ----- internet radio -----

    def m_getInternetRadioStations(self, p, user):
        with self.db() as conn:
            rows = conn.execute("SELECT * FROM radio_stations ORDER BY name COLLATE NOCASE").fetchall()
        return {"internetRadioStations": {"internetRadioStation": [
            {"id": f"rs-{r['id']}", "name": r["name"], "streamUrl": r["stream_url"], "homePageUrl": r["home_url"]}
            for r in rows]}}

    @staticmethod
    def _url(v: str | None, need: bool = True) -> str | None:
        from .subsonic import Fail

        v = (v or "").strip()
        if not v:
            return None
        if not v.lower().startswith(("http://", "https://")) or len(v) > 2000:
            raise Fail(0, "That isn’t a web address")
        return v

    def _station(self, conn, sid: str):
        from .subsonic import not_found

        n = sid[3:] if sid.startswith("rs-") else sid
        row = conn.execute("SELECT * FROM radio_stations WHERE id = ?", (int(n),)).fetchone() if n.isdigit() else None
        if not row:
            raise not_found("No such station")
        return row

    def m_createInternetRadioStation(self, p, user):
        self._admin(user, "add radio stations")
        stream = self._url(p.need("streamUrl"))
        with self.db() as conn:
            conn.execute("INSERT INTO radio_stations(name, stream_url, home_url, added_by, added_at) VALUES(?, ?, ?, ?, ?)",
                         (p.need("name")[:200], stream, self._url(p.get("homepageUrl") or p.get("homePageUrl")), user.id, time.time()))
        return {}

    def m_updateInternetRadioStation(self, p, user):
        self._admin(user, "change radio stations")
        with self.db() as conn:
            row = self._station(conn, p.need("id"))
            conn.execute("UPDATE radio_stations SET name = ?, stream_url = ?, home_url = ? WHERE id = ?",
                         (p.need("name")[:200], self._url(p.need("streamUrl")),
                          self._url(p.get("homepageUrl") or p.get("homePageUrl")), row["id"]))
        return {}

    def m_deleteInternetRadioStation(self, p, user):
        self._admin(user, "remove radio stations")
        with self.db() as conn:
            conn.execute("DELETE FROM radio_stations WHERE id = ?", (self._station(conn, p.need("id"))["id"],))
        return {}

    # ----- chat -----

    def m_getChatMessages(self, p, user):
        since = p.int("since", 0, 0, 10**14)  # milliseconds, as the messages give their time
        with self.db() as conn:
            rows = conn.execute("""SELECT c.*, u.username FROM chat_messages c JOIN users u ON u.id = c.user_id
                                   WHERE CAST(c.at * 1000 AS INTEGER) > ? ORDER BY c.at DESC LIMIT 200""", (since,)).fetchall()
        return {"chatMessages": {"chatMessage": [
            {"username": r["username"], "time": int(r["at"] * 1000), "message": r["message"]} for r in rows]}}

    def m_addChatMessage(self, p, user):
        msg = p.need("message").strip()[:1000]
        with self.db() as conn:
            if msg:
                conn.execute("INSERT INTO chat_messages(user_id, message, at) VALUES(?, ?, ?)", (user.id, msg, time.time()))
                conn.execute("DELETE FROM chat_messages WHERE id <= (SELECT id FROM chat_messages ORDER BY id DESC LIMIT 1 OFFSET ?)",
                             (CHAT_KEEP,))
        return {}

    # ----- podcasts -----

    def _channel_row(self, conn, cid: str, user):
        from .subsonic import not_found

        n = cid[3:] if cid.startswith("pc-") else cid
        row = conn.execute("SELECT * FROM podcasts WHERE id = ?", (int(n),)).fetchone() if n.isdigit() else None
        if not row:
            raise not_found("Podcast not found")
        return row

    @staticmethod
    def episode_num(eid: str) -> int | None:
        """An episode's own number from "pe-12", or from its stream id (EP_BASE + 12)."""
        if eid.startswith("pe-") and eid[3:].isdigit():
            return int(eid[3:])
        if eid.isdigit() and podcasts.is_episode(int(eid)):
            return int(eid) - podcasts.EP_BASE
        return None

    def _episode_row(self, conn, eid: str):
        from .subsonic import not_found

        n = self.episode_num(eid)
        row = conn.execute("SELECT * FROM episodes WHERE id = ?", (n,)).fetchone() if n is not None else None
        if not row:
            raise not_found("Episode not found")
        return row

    def episode(self, e, show, st=None) -> dict:
        from .subsonic import iso

        mime = e["mime"] or "audio/mpeg"
        suffix = {"audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/mp4": "m4a", "audio/x-m4a": "m4a", "audio/aac": "aac",
                  "audio/ogg": "ogg", "audio/opus": "opus", "audio/wav": "wav", "audio/flac": "flac"}.get(mime, "mp3")
        return {
            "id": f"pe-{e['id']}", "streamId": str(podcasts.EP_BASE + e["id"]), "channelId": f"pc-{show['id']}",
            "parent": f"pc-{show['id']}", "isDir": False, "title": e["title"], "album": show["title"],
            "artist": show["author"] or show["title"], "description": podcasts.plain(e["description"] or "", 2000),
            "publishDate": iso(e["published_at"]), "status": "completed", "coverArt": f"pc-{show['id']}",
            "duration": int(round(e["duration"] or 0)), "size": e["size"], "contentType": mime, "suffix": suffix,
            "type": "podcast", "mediaType": "song", "year": time.gmtime(e["published_at"]).tm_year if e["published_at"] else None,
            "genre": "Podcast", "created": iso(e["published_at"]),
            "bookmarkPosition": int(st["position"] * 1000) if st and st["position"] else None,
            "played": None,
        }

    def _states(self, conn, uid: int) -> dict:
        return {r["episode_id"]: r for r in conn.execute(
            "SELECT episode_id, position, finished FROM episode_state WHERE user_id = ?", (uid,))}

    def _channel(self, conn, show, uid: int, episodes: bool, states: dict) -> dict:
        out = {"id": f"pc-{show['id']}", "url": show["feed_url"], "title": show["title"],
               "description": podcasts.plain(show["description"] or "", 2000), "coverArt": f"pc-{show['id']}",
               "originalImageUrl": show["image_url"], "status": "error" if show["error"] else "completed",
               "errorMessage": show["error"]}
        if episodes:
            rows = conn.execute("SELECT * FROM episodes WHERE podcast_id = ? ORDER BY published_at DESC LIMIT 500",
                                (show["id"],)).fetchall()
            out["episode"] = [self.episode(e, show, states.get(e["id"])) for e in rows]
        return out

    def m_getPodcasts(self, p, user):
        with self.db() as conn:
            states = self._states(conn, user.id)
            if p.get("id"):
                shows = [self._channel_row(conn, p.get("id"), user)]
            else:
                shows = conn.execute("""SELECT p.* FROM podcasts p JOIN podcast_subs s ON s.podcast_id = p.id AND s.user_id = ?
                                        ORDER BY p.title COLLATE NOCASE""", (user.id,)).fetchall()
            return {"podcasts": {"channel": [self._channel(conn, s, user.id, p.flag("includeEpisodes", True), states)
                                             for s in shows]}}

    def m_getNewestPodcasts(self, p, user):
        with self.db() as conn:
            states = self._states(conn, user.id)
            rows = conn.execute("""SELECT e.* FROM episodes e JOIN podcast_subs s ON s.podcast_id = e.podcast_id AND s.user_id = ?
                                   ORDER BY e.published_at DESC LIMIT ?""", (user.id, p.int("count", 20, 1, 500))).fetchall()
            shows = {r["id"]: r for r in conn.execute("SELECT * FROM podcasts WHERE id IN (SELECT podcast_id FROM podcast_subs WHERE user_id = ?)",
                                                         (user.id,))}
        return {"newestPodcasts": {"episode": [self.episode(e, shows[e["podcast_id"]], states.get(e["id"]))
                                               for e in rows if e["podcast_id"] in shows]}}

    def m_getPodcastEpisode(self, p, user):
        with self.db() as conn:
            e = self._episode_row(conn, p.need("id"))
            show = conn.execute("SELECT * FROM podcasts WHERE id = ?", (e["podcast_id"],)).fetchone()
            st = podcasts.state(conn, user.id, e["id"])
        return {"podcastEpisode": self.episode(e, show, st)}

    def m_refreshPodcasts(self, p, user):
        with self.db() as conn:
            pids = [r[0] for r in conn.execute("SELECT DISTINCT podcast_id FROM podcast_subs WHERE user_id = ?", (user.id,))]
        db_path = self.cfg.db_path
        threading.Thread(target=lambda: [podcasts.refresh(db_path, pid) for pid in pids], daemon=True,
                         name="podcast-refresh").start()
        return {}

    def m_createPodcastChannel(self, p, user):
        from .subsonic import Fail

        url = p.need("url").strip()
        try:
            feed = podcasts.feed_for(url if url.lower().startswith("http") else f"https://{url}")
            show = podcasts.fetch_show(feed)
        except podcasts.FeedError as e:
            raise Fail(0, str(e))
        except (OSError, ValueError):
            raise Fail(0, "Couldn’t reach that podcast. Check the link, or try again in a moment.")
        with self.db() as conn:
            pid = podcasts.store(conn, feed, show)
            podcasts.follow(conn, user.id, pid)
        return {}

    def m_deletePodcastChannel(self, p, user):
        with self.db() as conn:
            podcasts.unfollow(conn, user.id, self._channel_row(conn, p.need("id"), user)["id"])
        return {}

    def m_downloadPodcastEpisode(self, p, user):
        """Shelf streams episodes from the show's host, so "downloading" one keeps it in Your Episodes."""
        with self.db() as conn:
            podcasts.save(conn, user.id, self._episode_row(conn, p.need("id"))["id"], True)
        return {}

    def m_deletePodcastEpisode(self, p, user):
        with self.db() as conn:
            podcasts.save(conn, user.id, self._episode_row(conn, p.need("id"))["id"], False)
        return {}

    async def episode_stream(self, eid: str, range_header: str | None):
        from .subsonic import CORS, Fail

        with self.db() as conn:
            e = self._episode_row(conn, eid)
        try:
            upstream, keep, mime = await asyncio.to_thread(podcasts.open_episode, e, range_header)
        except podcasts.HostError as err:
            raise Fail(0, str(err))
        return StreamingResponse(podcasts.body(upstream), status_code=upstream.status, media_type=mime,
                                 headers={**keep, **CORS, "Cache-Control": "no-store"})

    def show_cover_path(self, cid: str, size: int) -> Path | None:
        with self.db() as conn:
            if cid.startswith("pc-"):
                show = self._channel_row(conn, cid, None)
            else:
                e = self._episode_row(conn, cid)
                show = conn.execute("SELECT * FROM podcasts WHERE id = ?", (e["podcast_id"],)).fetchone()
        art = podcasts.art_path(self.cfg.data_dir, show) if show else None
        return covers.get_cover(self.cfg.cover_dir, f"file:{art}", size) if art else None

    # ----- the play queue, by position -----

    def _save_queue(self, user, ids: list[str], index: int | None, position: int, client: str) -> None:
        with self.db() as conn:
            if not ids:
                set_meta(conn, f"subsonic_queue:{user.id}", "null")
                return
            set_meta(conn, f"subsonic_queue:{user.id}", json.dumps({
                "ids": ids, "index": index, "current": ids[index] if index is not None else None,
                "position": position, "at": time.time(), "by": client}))

    def m_savePlayQueueByIndex(self, p, user):
        from .subsonic import Fail

        ids = p.all("id")[:2000]
        if not ids:
            if p.get("currentIndex") not in (None, ""):
                raise Fail(10, "currentIndex must not be set without songs")
            self._save_queue(user, [], None, 0, p.get("c") or "app")
            return {}
        raw = p.get("currentIndex")
        try:
            index = int(raw)
        except (TypeError, ValueError):
            raise Fail(10, "Required parameter is missing: currentIndex")
        if not 0 <= index < len(ids):
            raise Fail(10, "currentIndex is outside the queue")
        self._save_queue(user, ids, index, p.int("position", 0), p.get("c") or "app")
        return {}

    def m_getPlayQueueByIndex(self, p, user):
        from .subsonic import TRACKS, iso

        with self.db() as conn:
            saved = json.loads(get_meta(conn, f"subsonic_queue:{user.id}") or "null")
            if not saved or not saved.get("ids"):
                return {"playQueueByIndex": {"username": user.username, "changed": iso(time.time()), "changedBy": ""}}
            ids = [i for i in saved["ids"] if i.isdigit()]
            rows = {r["id"]: r for r in conn.execute(f"{TRACKS} WHERE t.id IN ({','.join('?' * len(ids))})",
                                                     [int(i) for i in ids])} if ids else {}
            ctx = self._ctx(conn, user.id)
        index = saved.get("index")
        if index is None and saved.get("current") in saved["ids"]:
            index = saved["ids"].index(saved["current"])
        kept, new_index = [], None
        for n, i in enumerate(saved["ids"]):
            if i.isdigit() and int(i) in rows:
                if n == index:
                    new_index = len(kept)
                kept.append(self.song(rows[int(i)], ctx))
        return {"playQueueByIndex": {"currentIndex": new_index, "position": saved.get("position", 0),
                                     "username": user.username, "changed": iso(saved["at"]),
                                     "changedBy": saved.get("by") or "", "entry": kept}}

    # ----- playback reports -----

    def m_reportPlayback(self, p, user):
        from .subsonic import Fail

        mid, kind, state = p.need("mediaId"), (p.need("mediaType") or "song").lower(), p.need("state").lower()
        if state not in STATES:
            raise Fail(0, f"Unknown state: {state}")
        if kind not in ("song", "podcast"):
            raise Fail(0, f"Unknown media type: {kind}")
        try:
            rate = max(0.25, min(4.0, float(p.get("playbackRate") or 1)))
        except ValueError:
            rate = 1.0
        pos = p.int("positionMs", 0, 0, 10**9)
        now = time.time()
        with self.db() as conn:
            if kind == "podcast":
                e = self._episode_row(conn, mid)
                track_id, length = podcasts.EP_BASE + e["id"], e["duration"] or 0
                if state in ("paused", "stopped", "playing"):
                    podcasts.keep_place(conn, user.id, e["id"], pos / 1000, length)
            else:
                row = self._track_row(conn, mid)
                track_id, length = row["id"], row["duration"] or 0
        # How long it's really been heard: the wall clock while playing, at its speed.
        was = self._listening.get(user.id)
        if not was or was["track"] != track_id or state == "starting":
            was = {"track": track_id, "heard": 0.0, "counted": False, "state": state, "at": now}
        elif was["state"] == "playing":
            was["heard"] += min(now - was["at"], 600) * was.get("rate", 1.0)
        was.update(state=state, at=now, rate=rate, pos=pos)
        self._listening[user.id] = was
        if kind == "song" and not was["counted"] and not p.flag("ignoreScrobble", False) and length and \
                was["heard"] >= min(length / 2, 240):
            was["counted"] = True
            self._count_play(user, track_id, now)
        if state == "stopped":
            self.now_playing.pop(user.id, None)
            self._listening.pop(user.id, None)
        else:
            self.now_playing[user.id] = {"track": track_id, "at": now, "player": p.get("c") or "app", "state": state,
                                         "positionMs": pos, "rate": rate}
        return {}

    def _count_play(self, user, track_id: int, when: float) -> None:
        with self.db() as conn:
            row = conn.execute("SELECT album_key FROM tracks WHERE id = ?", (track_id,)).fetchone()
            if not row:
                return
            conn.execute("INSERT INTO plays(track_id, album_key, played_at, user_id) VALUES(?, ?, ?, ?)",
                         (track_id, row["album_key"], when, user.id))
        if self.scrobbler:
            self.scrobbler.queue(user.id, track_id, when)
        self.on_played(user.id, track_id)

    def now_playing_extra(self, np: dict, now: float) -> dict:
        if "state" not in np:
            return {}
        pos = np["positionMs"]
        if np["state"] == "playing":
            pos += int((now - np["at"]) * 1000 * np["rate"])
        return {"state": np["state"], "positionMs": pos, "playbackRate": np["rate"]}

    # ----- songs that sound alike -----

    def _vectors(self, conn):
        return sound.library_vectors(self.cfg.db_path)

    def _match(self, conn, ids_sims: list[tuple[int, float]], user) -> list[dict]:
        from .subsonic import TRACKS

        if not ids_sims:
            return []
        ids = [i for i, _ in ids_sims]
        rows = {r["id"]: r for r in conn.execute(f"{TRACKS} WHERE t.id IN ({','.join('?' * len(ids))})", ids)}
        ctx = self._ctx(conn, user.id)
        return [{"entry": self.song(rows[i], ctx), "similarity": round(s, 4) if s >= 0 else -1}
                for i, s in ids_sims if i in rows]

    def m_getSonicSimilarTracks(self, p, user):
        import numpy as np

        count = p.int("count", 10, 1, 500)
        with self.db() as conn:
            seed = self._track_row(conn, p.need("id"))
            vecs = self._vectors(conn)
            if seed["id"] not in vecs:  # not measured yet: alike by artist and genre, without a score
                from .subsonic import Params
                picks = self._similar(Params([("id", str(seed["id"])), ("count", str(count))]), user)
                return {"sonicMatch": [{"entry": s, "similarity": -1} for s in picks]}
            ids = [i for i in vecs if i != seed["id"]]
            if not ids:
                return {"sonicMatch": []}
            sims = np.array([vecs[i] for i in ids]) @ vecs[seed["id"]]
            top = np.argsort(-sims)[:count]
            return {"sonicMatch": self._match(conn, [(ids[k], (float(sims[k]) + 1) / 2) for k in top], user)}

    def m_findSonicPath(self, p, user):
        """From one song to another through songs that sound like the way between them: each
        step is the song nearest a point part way from the first song's sound to the last's."""
        import numpy as np

        from .subsonic import Fail

        count = p.int("count", 25, 2, 200)
        with self.db() as conn:
            a = self._track_row(conn, p.need("startSongId"))
            b = self._track_row(conn, p.need("endSongId"))
            vecs = self._vectors(conn)
            if a["id"] not in vecs or b["id"] not in vecs:
                raise Fail(0, "Shelf hasn’t listened to one of those songs yet: try again once the library check is done")
            ids = [i for i in vecs if i not in (a["id"], b["id"])]
            m = np.array([vecs[i] for i in ids]) if ids else np.zeros((0, len(vecs[a["id"]])))
            va, vb = vecs[a["id"]], vecs[b["id"]]
            used: set[int] = set()
            path = [a["id"]]
            for k in range(1, count - 1):
                if len(used) >= len(ids):
                    break
                t = k / (count - 1)
                target = (1 - t) * va + t * vb
                target /= np.linalg.norm(target) or 1
                sims = m @ target
                for j in np.argsort(-sims):
                    if ids[j] not in used:
                        used.add(ids[j])
                        path.append(ids[j])
                        break
            path.append(b["id"])
            return {"sonicMatch": self._match(conn, [(i, (float(vecs[i] @ va) + 1) / 2) for i in path], user)}

    def sonic_similar(self, conn, seed_id: int, count: int, exclude_album: str | None) -> list[int] | None:
        """For getSimilarSongs: the songs that sound most like the seed, from other albums first,
        or None if the seed hasn't been measured."""
        import numpy as np

        vecs = self._vectors(conn)
        if seed_id not in vecs:
            return None
        ids = [i for i in vecs if i != seed_id]
        if not ids:
            return []
        sims = np.array([vecs[i] for i in ids]) @ vecs[seed_id]
        order = [ids[k] for k in np.argsort(-sims)[:count * 3]]
        if exclude_album:
            albums = {r[0]: r[1] for r in conn.execute(
                f"SELECT id, album_key FROM tracks WHERE id IN ({','.join('?' * len(order))})", order)} if order else {}
            order = sorted(order, key=lambda i: albums.get(i) == exclude_album)
        return order[:count]

    def similar_artists(self, conn, name: str, count: int) -> list[str]:
        """Artists whose songs sound most like this one's, on average; for a library not yet
        listened to, the artists sharing the most genres with them."""
        import numpy as np

        rows = conn.execute("SELECT t.id, t.sound, t.genre, a.artist FROM tracks t JOIN albums a ON a.key = t.album_key").fetchall()
        key = (len(rows), sum(r["id"] for r in rows if r["sound"]))
        if self._artist_sound["key"] != key:
            vecs = sound.vectors(rows)
            by: dict[str, list] = {}
            genres: dict[str, set] = {}
            spelled: dict[str, str] = {}
            for r in rows:
                for n in credits.names(r["artist"]) or [r["artist"]]:
                    f = videos.fold(n)
                    spelled.setdefault(f, n)
                    if r["id"] in vecs:
                        by.setdefault(f, []).append(vecs[r["id"]])
                    if r["genre"]:
                        genres.setdefault(f, set()).update(g.strip().lower() for g in r["genre"].replace(";", "/").split("/") if g.strip())
            centres = {}
            for f, vs in by.items():
                c = np.mean(vs, axis=0)
                n = np.linalg.norm(c)
                if n:
                    centres[f] = c / n
            self._artist_sound = {"key": key, "vecs": centres, "genres": genres, "names": spelled}
        st = self._artist_sound
        me = videos.fold(name)
        if me in st["vecs"]:
            others = [(f, float(v @ st["vecs"][me])) for f, v in st["vecs"].items() if f != me]
        else:
            mine = st["genres"].get(me, set())
            others = [(f, len(mine & g) / (len(mine | g) or 1)) for f, g in st["genres"].items() if f != me and mine & g]
        others.sort(key=lambda x: -x[1])
        return [st["names"][f] for f, _ in others[:count]]

    # ----- conversions the app chooses (OpenSubsonic transcoding) -----

    def _source(self, row) -> dict:
        suffix = Path(row["path"]).suffix.lstrip(".").lower()
        codec = (row["codec"] or suffix).lower()
        return {"protocol": "http", "container": CONTAINERS.get(suffix, suffix), "codec": CODECS.get(codec, codec),
                "audioChannels": (json.loads(row["extra"] or "{}").get("channels") if "extra" in row.keys() else None) or 2,
                "audioBitrate": row["bitrate"] or 0, "audioSamplerate": row["sample_rate"] or 0,
                "audioBitdepth": row["bits"] or 0, "audioProfile": ""}

    @staticmethod
    def _meets(src: dict, limits: list) -> tuple[bool, str]:
        for lim in limits or []:
            name, cmp, values = lim.get("name"), lim.get("comparison"), [str(v) for v in lim.get("values") or []]
            have = {"audioChannels": src["audioChannels"], "audioBitrate": src["audioBitrate"],
                    "audioSamplerate": src["audioSamplerate"], "audioBitdepth": src["audioBitdepth"],
                    "audioProfile": src["audioProfile"]}.get(name)
            if have in (None, 0, "") or not values:
                continue  # unknown: don't hold it against the file
            try:
                if cmp == "Equals":
                    ok = str(have) in values
                elif cmp == "NotEquals":
                    ok = str(have) not in values
                elif cmp == "LessThanEqual":
                    ok = float(have) <= float(values[0])
                elif cmp == "GreaterThanEqual":
                    ok = float(have) >= float(values[0])
                else:
                    ok = True
            except ValueError:
                ok = True
            if not ok and lim.get("required", True):
                return False, f"{name}NotSupported"
        return True, ""

    def decide(self, row, info: dict) -> dict:
        src = self._source(row)
        profiles = info.get("codecProfiles") or []
        limits = lambda codec: [l for cp in profiles if (cp.get("name") or "").lower() == codec for l in cp.get("limitations") or []]  # noqa: E731
        max_rate = int(info.get("maxAudioBitrate") or 0)
        reasons = []
        for dp in info.get("directPlayProfiles") or []:
            containers = [c.lower() for c in dp.get("containers") or []]
            codecs = [c.lower() for c in dp.get("audioCodecs") or []]
            protocols = [x.lower() for x in dp.get("protocols") or []]
            if containers and src["container"] not in containers and Path(row["path"]).suffix.lstrip(".").lower() not in containers:
                reasons.append("ContainerNotSupported")
            elif codecs and src["codec"] not in codecs:
                reasons.append("AudioCodecNotSupported")
            elif protocols and "http" not in protocols:
                reasons.append("ProtocolNotSupported")
            elif dp.get("maxAudioChannels") and src["audioChannels"] > int(dp["maxAudioChannels"]):
                reasons.append("AudioChannelsNotSupported")
            elif max_rate and src["audioBitrate"] > max_rate:
                reasons.append("AudioBitrateNotSupported")
            else:
                ok, why = self._meets(src, limits(src["codec"]))
                if ok:
                    return {"canDirectPlay": True, "canTranscode": False, "sourceStream": src}
                reasons.append(why)
        cap = int(info.get("maxTranscodingAudioBitrate") or 0) or max_rate
        for tp in info.get("transcodingProfiles") or []:
            if (tp.get("protocol") or "http").lower() != "http":
                continue
            codec = transcode.live_codec(tp.get("audioCodec")) or transcode.live_codec(tp.get("container"))
            if not codec:
                continue
            kbps = transcode.LIVE[codec][3]
            for lim in limits(codec):
                if lim.get("name") == "audioBitrate" and lim.get("comparison") == "LessThanEqual" and lim.get("values"):
                    try:
                        kbps = min(kbps or 10**6, int(float(lim["values"][0]) // 1000))
                    except ValueError:
                        pass
            if cap and codec != "flac":
                kbps = min(kbps, cap // 1000)
            kbps = max(32, kbps) if codec != "flac" else 0
            out = {"protocol": "http", "container": transcode.LIVE[codec][1] if codec != "aac" else "aac", "codec": codec,
                   "audioChannels": min(src["audioChannels"], int(tp.get("maxAudioChannels") or 2)),
                   "audioBitrate": kbps * 1000, "audioSamplerate": 48000 if codec == "opus" else src["audioSamplerate"],
                   "audioBitdepth": src["audioBitdepth"] if codec == "flac" else 0, "audioProfile": ""}
            return {"canDirectPlay": False, "canTranscode": True, "transcodeReason": reasons or ["NoDirectPlayProfile"],
                    "transcodeParams": f"{codec}-{kbps}", "sourceStream": src, "transcodeStream": out}
        return {"canDirectPlay": False, "canTranscode": False, "transcodeReason": reasons or ["NoDirectPlayProfile"],
                "errorReason": "None of the app’s formats can be made from this file", "sourceStream": src}

    def m_getTranscodeDecision(self, p, user):
        from .subsonic import Fail

        kind = (p.need("mediaType") or "song").lower()
        info = getattr(p, "body", None)
        if not isinstance(info, dict):
            raise Fail(10, "The app’s abilities (ClientInfo) must be sent as JSON in the body")
        with self.db() as conn:
            if kind == "podcast":
                e = self._episode_row(conn, p.need("mediaId"))
                return {"transcodeDecision": {"canDirectPlay": True, "canTranscode": False, "sourceStream": {
                    "protocol": "http", "container": podcasts.codec(e["mime"] or "audio/mpeg"),
                    "codec": podcasts.codec(e["mime"] or "audio/mpeg")}}}
            row = self._track_row(conn, p.need("mediaId"))
        return {"transcodeDecision": self.decide(row, info)}

    async def transcode_stream(self, p):
        """getTranscodeStream: the conversion getTranscodeDecision chose, from `offset` seconds in."""
        from .subsonic import CORS, Fail

        if (p.get("mediaType") or "song").lower() == "podcast":
            return await self.episode_stream(p.need("mediaId"), None)
        params = p.need("transcodeParams")
        codec, _, kbps = params.partition("-")
        if codec not in transcode.LIVE or not kbps.isdigit():
            raise Fail(0, "Those transcodeParams didn’t come from Shelf")
        row = self.file_for(p.need("mediaId"))
        try:
            offset = max(0.0, float(p.get("offset") or 0))
        except ValueError:
            offset = 0.0
        return await self.live_response(Path(row["path"]), codec, int(kbps), offset)

    async def live_response(self, path: Path, codec: str, kbps: int, offset: float):
        from .subsonic import CORS, Fail

        gen = transcode.live(path, codec, kbps, offset)
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

        return StreamingResponse(body(), media_type=transcode.LIVE[codec][2], headers={**CORS, "Cache-Control": "no-store"})

    # ----- things Shelf can't do -----

    def m_jukeboxControl(self, p, user):
        from .subsonic import Fail

        raise Fail(50, "Shelf doesn’t play through the server’s own speakers. Use Connect in the Shelf app to play on another device.")

    def m_getVideoInfo(self, p, user):
        from .subsonic import not_found

        raise not_found("Shelf has no videos of its own")

    m_getCaptions = m_getVideoInfo
    m_hls = m_getVideoInfo

