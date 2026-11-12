"""Webhooks: Shelf tells another program (Home Assistant, a script, a chat bot) when something
happens: a song starts, the music pauses, a listen counts, the library changes."""

import asyncio
import hashlib
import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from shelf import webhooks
from shelf.connect import Hub


class Catcher:
    """A little web server that keeps what's posted to it."""

    def __init__(self, status=200):
        self.got = []
        self.status = status
        catcher = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                catcher.got.append({"path": self.path, "headers": dict(self.headers), "body": body,
                                    "json": json.loads(body)})
                self.send_response(catcher.status)
                self.end_headers()

            def log_message(self, *a):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/hook"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


@pytest.fixture()
def catcher():
    c = Catcher()
    yield c
    c.close()


def login(c, username="admin", password="hunter2"):
    assert c.post("/api/login", json={"username": username, "password": password}).status_code == 200


def drain(client):
    client.app.state.webhooks.drain(5)


# ---------- unit ----------

def test_signed_when_there_is_a_secret(catcher):
    body = webhooks.payload("played", {"track": {"title": "Opening"}})
    status = webhooks.deliver(catcher.url, body, "event", secret="s3cret")
    assert status == "200"
    got = catcher.got[0]
    assert got["json"]["event"] == "played" and got["json"]["track"]["title"] == "Opening"
    want = "sha256=" + hmac.new(b"s3cret", got["body"], hashlib.sha256).hexdigest()
    assert got["headers"]["X-Shelf-Signature"] == want
    assert got["headers"]["X-Shelf-Event"] == "event"


def test_a_failing_hook_reports_why():
    assert webhooks.deliver("http://127.0.0.1:9/nothing", b"{}", "test").startswith("Couldn’t reach it")
    c = Catcher(status=404)
    try:
        assert webhooks.deliver(c.url, b"{}", "test") == "404"
    finally:
        c.close()


def test_only_web_addresses():
    assert webhooks.check_url("http://homeassistant.local:8123/api/webhook/abc") == "http://homeassistant.local:8123/api/webhook/abc"
    assert webhooks.check_url(" https://example.org/x ") == "https://example.org/x"
    for bad in ("ftp://x", "file:///etc/passwd", "homeassistant.local", "", "http://"):
        with pytest.raises(ValueError):
            webhooks.check_url(bad)


def test_the_hub_says_when_the_music_starts_and_pauses():
    seen = []
    hub = Hub(on_change=lambda event, track, device: seen.append((event, track["id"] if track else None, device)))
    song = lambda i: {"id": i, "title": f"Song {i}", "artist": "Band"}  # noqa: E731

    class Dev:
        id, name = "d1", "Kitchen"

    hub.active = "d1"
    hub.devices = {"d1": Dev()}

    async def state(**s):
        await hub._state_changed(Dev(), s)

    hub.queue = {"tracks": [song(1), song(2)]}
    asyncio.run(state(index=0, playing=True, position=1))
    asyncio.run(state(index=0, playing=True, position=4))  # only the place moved: nothing new
    asyncio.run(state(index=1, playing=True, position=0))
    asyncio.run(state(index=1, playing=False, position=30))
    assert seen == [("playing", 1, "Kitchen"), ("playing", 2, "Kitchen"), ("paused", 2, "Kitchen")]


# ---------- through the server ----------

def test_admin_adds_tests_and_removes_a_hook(client, catcher):
    login(client)
    assert client.post("/api/admin/webhooks", json={"url": "not a url", "events": ["played"]}).status_code == 400
    assert client.post("/api/admin/webhooks", json={"url": catcher.url, "events": ["nonsense"]}).status_code == 400
    r = client.post("/api/admin/webhooks", json={"url": catcher.url, "events": ["played", "library"], "secret": "x"})
    assert r.status_code == 200
    hook = r.json()
    assert hook["events"] == ["played", "library"] and hook["secret"] is True  # the secret itself isn't sent back
    t = client.post(f"/api/admin/webhooks/{hook['id']}/test")
    assert t.status_code == 200 and t.json()["status"] == "200"
    assert catcher.got[-1]["json"]["event"] == "test"
    listed = client.get("/api/admin/webhooks").json()
    assert listed["hooks"][0]["lastStatus"] == "200"
    assert {e["id"] for e in listed["events"]} == {"playing", "paused", "played", "library"}
    assert client.delete(f"/api/admin/webhooks/{hook['id']}").status_code == 200
    assert client.get("/api/admin/webhooks").json()["hooks"] == []


def test_only_admins(client):
    login(client)
    client.post("/api/users", json={"username": "kid", "password": "kidpass1"})
    client.post("/api/logout")
    login(client, "kid", "kidpass1")
    assert client.get("/api/admin/webhooks").status_code == 403
    assert client.post("/api/admin/webhooks", json={"url": "http://x.org", "events": ["played"]}).status_code == 403


def test_your_listens_go_to_your_hooks_only(client, catcher):
    login(client)
    client.post("/api/admin/webhooks", json={"url": catcher.url, "events": ["played"]})
    client.post("/api/users", json={"username": "kid", "password": "kidpass1"})
    tid = client.get("/api/tracks/random?limit=1").json()[0]["id"]
    assert client.post(f"/api/tracks/{tid}/played").status_code == 200
    client.post("/api/logout")
    login(client, "kid", "kidpass1")
    client.post(f"/api/tracks/{tid}/played")  # someone else's listen
    drain(client)
    assert len(catcher.got) == 1
    sent = catcher.got[0]["json"]
    assert sent["event"] == "played" and sent["user"] == "admin" and sent["track"]["id"] == tid
    assert {"title", "artist", "album", "duration"} <= set(sent["track"])


def test_new_music_is_announced(client, catcher, library):
    from conftest import make_track

    login(client)
    client.post("/api/admin/webhooks", json={"url": catcher.url, "events": ["library"]})
    make_track(library / "Newcomer" / "Debut" / "01 Hello.mp3", title="Hello", artist="Newcomer", album="Debut", track=1)
    client.app.state.scanner.run_once()
    drain(client)
    sent = [g["json"] for g in catcher.got if g["json"]["event"] == "library"]
    assert sent and sent[0]["added"] == 1
    assert sent[0]["albums"] == [{"title": "Debut", "artist": "Newcomer"}]
    # A scan that finds nothing new says nothing.
    client.app.state.scanner.run_once()
    drain(client)
    assert len([g for g in catcher.got if g["json"]["event"] == "library"]) == 1
