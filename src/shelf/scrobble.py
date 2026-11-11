"""Scrobbling: send each listen to ListenBrainz (listenbrainz.org), for people who connect it.

ListenBrainz is the open, non-profit counterpart to Last.fm. Each person pastes their own
user token (from listenbrainz.org/settings) in Settings; their listens then go there, with
the artist, title, album and length of the song and when it was played. Nothing is sent for
anyone who hasn't connected it.

Listens wait in a queue in the database and are sent in the background, so a slow or
unreachable ListenBrainz never holds up playback, and nothing is lost while it's down.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import __version__
from .db import session

log = logging.getLogger("shelf.scrobble")
API = "https://api.listenbrainz.org/1"
AGENT = f"Shelf/{__version__} (self-hosted music server)"


def _call(path: str, token: str, body: dict | None = None, timeout: float = 15) -> dict:
    req = urllib.request.Request(
        f"{API}/{path}", data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Token {token}", "Content-Type": "application/json", "User-Agent": AGENT},
        method="POST" if body is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def check_token(token: str) -> str:
    """The ListenBrainz user name for a token. ValueError if it isn't valid."""
    try:
        r = _call("validate-token", token)
    except urllib.error.URLError as e:
        raise ValueError(f"Couldn’t reach ListenBrainz: {e.reason if hasattr(e, 'reason') else e}") from e
    if not r.get("valid"):
        raise ValueError("ListenBrainz didn’t accept that token. Copy it again from listenbrainz.org/settings")
    return r.get("user_name") or ""


class Scrobbler:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._wake = threading.Event()
        self._stop = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._loop, name="shelf-scrobbler", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def queue(self, user_id: int, track_id: int, at: float) -> None:
        """A listen, for sending to each service this person has connected (ListenBrainz, Last.fm)."""
        with session(self.db_path) as conn:
            u = conn.execute("SELECT listenbrainz_token, lastfm_session FROM users WHERE id = ?", (user_id,)).fetchone()
            if not u:
                return
            for service, connected in (("listenbrainz", u["listenbrainz_token"]), ("lastfm", u["lastfm_session"])):
                if connected:
                    conn.execute("INSERT INTO scrobbles(user_id, track_id, played_at, service) VALUES(?, ?, ?, ?)",
                                 (user_id, track_id, at, service))
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.flush()
            except Exception:  # keep going; try again later
                log.exception("Scrobbling failed")
            self._wake.wait(300)
            self._wake.clear()

    def flush(self) -> int:
        return self._flush_listenbrainz() + self._flush_lastfm()

    def _flush_lastfm(self) -> int:
        from . import lastfm

        account = lastfm.keys(self.db_path)
        if not account:
            return 0
        with session(self.db_path) as conn:
            rows = conn.execute(
                """SELECT s.id, s.user_id, s.played_at, u.lastfm_session AS sk, t.title, t.artist, t.album, t.duration
                   FROM scrobbles s JOIN users u ON u.id = s.user_id JOIN tracks t ON t.id = s.track_id
                   WHERE s.service = 'lastfm' AND u.lastfm_session IS NOT NULL ORDER BY s.user_id, s.played_at LIMIT 500""").fetchall()
        sent = 0
        by_user: dict[int, list] = {}
        for r in rows:
            by_user.setdefault(r["user_id"], []).append(r)
        for uid, listens in by_user.items():
            for i in range(0, len(listens), 50):
                batch = listens[i:i + 50]
                try:
                    lastfm.scrobble(*account, batch[0]["sk"], [{"artist": r["artist"], "track": r["title"], "album": r["album"],
                                                               "timestamp": int(r["played_at"]), "duration": int(r["duration"] or 0)}
                                                              for r in batch])
                except lastfm.LastfmError as e:
                    if e.code in (4, 9, 14):  # the session was withdrawn: stop trying for this person
                        with session(self.db_path) as conn:
                            conn.execute("UPDATE users SET lastfm_session = NULL, lastfm_user = NULL WHERE id = ?", (uid,))
                            conn.execute("DELETE FROM scrobbles WHERE user_id = ? AND service = 'lastfm'", (uid,))
                        log.warning("Last.fm rejected user %s's session; disconnected", uid)
                    break  # anything else (rate limit, Last.fm down): they stay queued
                except (urllib.error.URLError, OSError):
                    break
                with session(self.db_path) as conn:
                    conn.executemany("DELETE FROM scrobbles WHERE id = ?", [(r["id"],) for r in batch])
                sent += len(batch)
        if sent:
            log.info("Sent %d listens to Last.fm", sent)
        return sent

    def _flush_listenbrainz(self) -> int:
        with session(self.db_path) as conn:
            rows = conn.execute(
                """SELECT s.id, s.user_id, s.played_at, u.listenbrainz_token AS token,
                          t.title, t.artist, t.album, t.duration
                   FROM scrobbles s JOIN users u ON u.id = s.user_id JOIN tracks t ON t.id = s.track_id
                   WHERE s.service = 'listenbrainz' AND u.listenbrainz_token IS NOT NULL
                   ORDER BY s.user_id, s.played_at LIMIT 500""").fetchall()
        sent = 0
        by_user: dict[int, list] = {}
        for r in rows:
            by_user.setdefault(r["user_id"], []).append(r)
        for uid, listens in by_user.items():
            payload = [{
                "listened_at": int(r["played_at"]),
                "track_metadata": {
                    "artist_name": r["artist"], "track_name": r["title"], "release_name": r["album"],
                    "additional_info": {"duration_ms": int((r["duration"] or 0) * 1000), "media_player": "Shelf",
                                        "submission_client": "Shelf", "submission_client_version": __version__},
                },
            } for r in listens]
            try:
                _call("submit-listens", listens[0]["token"], {"listen_type": "import" if len(payload) > 1 else "single",
                                                              "payload": payload})
            except urllib.error.HTTPError as e:
                if e.code == 401:  # token withdrawn: stop trying for this person
                    with session(self.db_path) as conn:
                        conn.execute("UPDATE users SET listenbrainz_token = NULL WHERE id = ?", (uid,))
                        conn.execute("DELETE FROM scrobbles WHERE user_id = ? AND service = 'listenbrainz'", (uid,))
                    log.warning("ListenBrainz rejected user %s's token; disconnected", uid)
                continue
            except (urllib.error.URLError, OSError):
                continue  # ListenBrainz is down: they stay queued
            with session(self.db_path) as conn:
                conn.executemany("DELETE FROM scrobbles WHERE id = ?", [(r["id"],) for r in listens])
            sent += len(listens)
        # Listens for songs that have since left the library can't be sent.
        with session(self.db_path) as conn:
            conn.execute("DELETE FROM scrobbles WHERE track_id NOT IN (SELECT id FROM tracks)")
        if sent:
            log.info("Sent %d listens to ListenBrainz", sent)
        return sent
