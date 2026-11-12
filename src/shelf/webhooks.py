"""Webhooks: Shelf tells another program when something happens, by sending it a little JSON
message (an HTTP POST). Home Assistant's "Webhook" automation trigger takes them as they are,
so lights can dim when the music starts, or a speaker turn on.

What can be sent:
- playing: a song starts (or starts again after a pause), on any device, from the live-playback
  hub (connect.py) that every app reports to;
- paused: the music pauses;
- played: a listen counts (as for play counts and scrobbling);
- library: a scan finds new, changed or removed songs, with the new albums.

Only admins add webhooks: the server sends to whatever address it's given, which mustn't be up
to everyone. The listening events are the admin's own (whoever added the hook); nobody else's
listening leaves the server this way. With a secret, each message is signed (X-Shelf-Signature:
sha256=HMAC of the body), so the receiver can tell it's from this Shelf.

Messages go out one at a time from a background thread, so nothing waits on a slow receiver.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import queue
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from . import __version__

log = logging.getLogger("shelf.webhooks")

EVENTS = [
    {"id": "playing", "label": "A song starts", "mine": True},
    {"id": "paused", "label": "The music pauses", "mine": True},
    {"id": "played", "label": "A listen counts", "mine": True},
    {"id": "library", "label": "New music in the library", "mine": False},
]
IDS = {e["id"] for e in EVENTS}
LISTENING = {e["id"] for e in EVENTS if e["mine"]}
TIMEOUT = 10


def check_url(url: str) -> str:
    url = (url or "").strip()
    u = urlsplit(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError("A webhook needs a web address, starting with http:// or https://.")
    return url


def check_events(events) -> list[str]:
    picked = [e for e in dict.fromkeys(events or []) if isinstance(e, str)]
    if not picked or any(e not in IDS for e in picked):
        raise ValueError("Pick what the webhook should hear about.")
    return picked


def payload(event: str, data: dict) -> bytes:
    return json.dumps({"event": event, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **data},
                      ensure_ascii=False).encode()


def deliver(url: str, body: bytes, event: str, secret: str = "") -> str:
    """Sends one message. The answer's status code ("200"), or why it didn't arrive."""
    headers = {"Content-Type": "application/json", "User-Agent": f"Shelf/{__version__}", "X-Shelf-Event": event}
    if secret:
        headers["X-Shelf-Signature"] = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers, method="POST"),
                                    timeout=TIMEOUT) as r:
            return str(r.status)
    except urllib.error.HTTPError as e:
        return str(e.code)
    except (OSError, ValueError) as e:
        return f"Couldn’t reach it ({getattr(e, 'reason', e)})"


def track_json(r) -> dict:
    """What a message says about a song."""
    get = r.get if isinstance(r, dict) else (lambda k, d=None: r[k] if k in r.keys() else d)
    return {"id": get("id"), "title": get("title"), "artist": get("artist"),
            "album": get("album_title") or get("album"), "albumId": get("album_id") or get("albumId"),
            "duration": round(get("duration") or 0, 1)}


def hook_json(r) -> dict:
    return {"id": r["id"], "url": r["url"], "events": json.loads(r["events"]), "secret": bool(r["secret"]),
            "lastAt": r["last_at"], "lastStatus": r["last_status"]}


class Sender:
    """Sends messages in the background, one at a time. `db` opens the database."""

    def __init__(self, db):
        self.db = db
        self._q: queue.Queue = queue.Queue()
        self._busy = 0
        self._lock = threading.Lock()
        threading.Thread(target=self._loop, name="webhooks", daemon=True).start()

    def emit(self, event: str, data: dict, user_id: int | None = None) -> int:
        """Queues the message for every hook that wants it: listening events to the user's own
        hooks only. How many were queued."""
        with self.db() as conn:
            rows = conn.execute("SELECT id, user_id, url, events, secret FROM webhooks").fetchall()
            name = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone() if user_id else None
        if name:
            data = {"user": name["username"], **data}
        body = payload(event, data)
        n = 0
        for r in rows:
            if event not in json.loads(r["events"]):
                continue
            if event in LISTENING and r["user_id"] != user_id:
                continue
            with self._lock:
                self._busy += 1
            self._q.put((r["id"], r["url"], r["secret"], event, body))
            n += 1
        return n

    def send_now(self, hook_id: int) -> str:
        """A test message to one hook, sent straight away. Its status."""
        with self.db() as conn:
            r = conn.execute("SELECT url, secret FROM webhooks WHERE id = ?", (hook_id,)).fetchone()
        status = deliver(r["url"], payload("test", {"text": "Shelf can reach this webhook."}), "test", r["secret"])
        self._record(hook_id, status)
        return status

    def drain(self, timeout: float = 10) -> bool:
        """Waits for the queue to empty (tests)."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            with self._lock:
                if self._busy == 0:
                    return True
            time.sleep(0.02)
        return False

    def _record(self, hook_id: int, status: str) -> None:
        with self.db() as conn:
            conn.execute("UPDATE webhooks SET last_at = ?, last_status = ? WHERE id = ?", (time.time(), status, hook_id))

    def _loop(self) -> None:
        while True:
            hook_id, url, secret, event, body = self._q.get()
            try:
                status = deliver(url, body, event, secret)
                if not status.isdigit() or not status.startswith("2"):
                    log.info("Webhook %s: %s", hook_id, status)
                self._record(hook_id, status)
            except Exception:  # keep the thread alive
                log.exception("Webhook %s failed", hook_id)
            finally:
                with self._lock:
                    self._busy -= 1
