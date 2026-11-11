"""Scrobbling to Last.fm: an admin adds the server's API account, each person connects theirs."""

import hashlib

from fastapi.testclient import TestClient

from shelf import lastfm


def login(c, username="admin", password="hunter2"):
    assert c.post("/api/login", json={"username": username, "password": password}).status_code == 200


def test_requests_are_signed_as_lastfm_asks():
    params = {"method": "auth.getSession", "api_key": "k", "token": "t", "format": "json"}
    expected = hashlib.md5("api_keykmethodauth.getSessiontokentsecret".encode()).hexdigest()
    assert lastfm.sign(params, "secret") == expected  # sorted, format left out, secret at the end


class FakeLastfm:
    def __init__(self):
        self.calls = []
        self.fail_session = False

    def __call__(self, params, post):
        self.calls.append(dict(params))
        m = params["method"]
        if m == "auth.getToken":
            return {"token": "tok123"}
        if m == "auth.getSession":
            return {"session": {"name": "rocker", "key": "sk-1"}}
        if m == "track.scrobble":
            if self.fail_session:
                return {"error": 9, "message": "Invalid session key"}
            return {"scrobbles": {"@attr": {"accepted": 1}}}
        raise AssertionError(m)


def test_connect_and_scrobble(client, monkeypatch):
    fake = FakeLastfm()
    monkeypatch.setattr(lastfm, "_request", fake)
    login(client)
    assert client.post("/api/me/lastfm/start").status_code == 409  # no API account yet
    assert client.patch("/api/admin/lastfm", json={"key": "k", "secret": "s"}).json() == {"configured": True}

    start = client.post("/api/me/lastfm/start").json()
    assert "api_key=k" in start["url"] and "token=tok123" in start["url"]
    assert client.post("/api/me/lastfm/finish").json() == {"lastfm": "rocker"}
    assert client.get("/api/session").json()["user"]["lastfm"] == "rocker"

    tracks = client.get("/api/tracks/random?limit=2").json()
    for t in tracks:
        client.post(f"/api/tracks/{t['id']}/played")
    sent = client.app.state.scrobbler.flush()
    assert sent == 2
    batch = fake.calls[-1]
    assert batch["method"] == "track.scrobble" and batch["sk"] == "sk-1" and "api_sig" in batch
    assert {batch["track[0]"], batch["track[1]"]} == {t["title"] for t in tracks}
    assert client.app.state.scrobbler.flush() == 0  # sent once

    # Last.fm withdrew the session: disconnected, and nothing more is queued for it.
    fake.fail_session = True
    client.post(f"/api/tracks/{tracks[0]['id']}/played")
    client.app.state.scrobbler.flush()
    assert client.get("/api/session").json()["user"]["lastfm"] is None


def test_lastfm_keys_are_admin_only(client):
    login(client)
    client.post("/api/users", json={"username": "sam", "password": "sam-pass"})
    sam = TestClient(client.app)
    login(sam, "sam", "sam-pass")
    assert sam.patch("/api/admin/lastfm", json={"key": "k", "secret": "s"}).status_code == 403
