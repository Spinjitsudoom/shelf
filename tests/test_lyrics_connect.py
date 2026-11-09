import time

import pytest
from mutagen.id3 import ID3, USLT
from starlette.websockets import WebSocketDisconnect

from shelf import lyrics



def tracks_by_title(client):
    out = {}
    for a in client.get("/api/albums").json():
        for t in client.get(f"/api/albums/{a['id']}").json()["tracks"]:
            out[t["title"]] = t
    return out


def login(client):
    assert client.post("/api/login", json={"password": "hunter2"}).status_code == 200


# ---------- lyrics ----------

def test_parse_lrc():
    lines = lyrics.parse_lrc("[ar:Band]\n[offset:+500]\n[00:01.50][00:10.00]Hello <00:02.00>there\n[00:05]\n")
    assert lines == [
        {"t": 1.0, "text": "Hello there"},
        {"t": 4.5, "text": ""},
        {"t": 9.5, "text": "Hello there"},
    ]
    assert lyrics.parse_lrc("just words\nno times") is None


def test_lyrics_from_lrc_file_and_tags(client, library):
    login(client)
    tracks = tracks_by_title(client)
    (library / "Band" / "2001 - First" / "01 Opening.lrc").write_text("[00:00.50]First line\n[00:01.20]Second line\n")
    tags = ID3(library / "Band" / "2001 - First" / "02 Closer.mp3")
    tags.add(USLT(encoding=3, lang="eng", desc="", text="Plain verse\nPlain chorus"))
    tags.save()

    r = client.get(f"/api/tracks/{tracks['Opening']['id']}/lyrics").json()
    assert r["kind"] == "synced" and r["source"] == "file"
    assert [l["text"] for l in r["lines"]] == ["First line", "Second line"]

    r = client.get(f"/api/tracks/{tracks['Closer']['id']}/lyrics").json()
    assert r == {"kind": "plain", "text": "Plain verse\nPlain chorus", "source": "file"}

    assert client.get(f"/api/tracks/{tracks['Late']['id']}/lyrics").json()["kind"] == "none"


def test_lyrics_from_lrclib_are_cached(client, library, monkeypatch):
    login(client)
    client.app.state.cfg.online_lyrics = True
    tracks = tracks_by_title(client)
    calls = []

    def fake(url):
        calls.append(url)
        if "Early" in url and "/get?" in url:
            return {"syncedLyrics": "[00:00.40]From the web", "plainLyrics": "From the web", "instrumental": False}
        return None if "/get?" in url else []

    monkeypatch.setattr(lyrics, "_fetch_json", fake)
    r = client.get(f"/api/tracks/{tracks['Early']['id']}/lyrics").json()
    assert r["kind"] == "synced" and r["source"] == "lrclib" and r["lines"][0]["text"] == "From the web"
    n = len(calls)
    client.get(f"/api/tracks/{tracks['Early']['id']}/lyrics")
    assert len(calls) == n, "second request should come from the cache"

    # A miss is remembered too, so the song isn't looked up on every play.
    assert client.get(f"/api/tracks/{tracks['Late']['id']}/lyrics").json()["kind"] == "none"
    n = len(calls)
    client.get(f"/api/tracks/{tracks['Late']['id']}/lyrics")
    assert len(calls) == n


def test_lyrics_offline_falls_back_to_files(client, library, monkeypatch):
    login(client)
    client.app.state.cfg.online_lyrics = True
    monkeypatch.setattr(lyrics, "_offline_until", 0.0)
    tracks = tracks_by_title(client)

    def down(url):
        raise OSError("network is unreachable")

    monkeypatch.setattr(lyrics, "_fetch_json", down)
    assert client.get(f"/api/tracks/{tracks['Late']['id']}/lyrics").json()["kind"] == "none"
    assert lyrics._offline_until > time.time()


# ---------- devices ----------

def hello(ws, dev_id, name="Test device", kind="computer"):
    ws.send_json({"type": "hello", "id": dev_id, "name": name, "kind": kind})
    msg = ws.receive_json()
    assert msg["type"] == "welcome"
    return msg


def recv_until(ws, kind):
    for _ in range(10):
        msg = ws.receive_json()
        if msg["type"] == kind:
            return msg
    raise AssertionError(f"no {kind} message")


def test_connect_requires_login(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/connect") as ws:
            ws.receive_json()


def test_connect_rejects_other_websites(client):
    login(client)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/connect", headers={"origin": "https://evil.example"}) as ws:
            ws.receive_json()


def test_connect_remote_control_and_transfer(client):
    login(client)
    track = {"id": 1, "title": "Opening", "duration": 200}
    with client.websocket_connect("/api/connect") as tv, client.websocket_connect("/api/connect") as phone:
        hello(tv, "tv-device-0001", "Living room", "tv")
        welcome = hello(phone, "phone-device-01", "Phone", "phone")
        assert {d["name"] for d in welcome["devices"]} == {"Living room", "Phone"}
        assert recv_until(tv, "devices")["active"] is None

        # The TV starts playing and reports its state; the phone sees it.
        tv.send_json({"type": "claim"})
        assert recv_until(phone, "devices")["active"] == "tv-device-0001"
        tv.send_json({"type": "state", "state": {"index": 0, "track": track, "playing": True, "position": 30,
                                                  "duration": 200, "shuffle": False, "repeat": "off"},
                      "queue": {"rev": 1, "tracks": [track], "original": None}})
        st = recv_until(phone, "state")
        assert st["state"]["position"] == 30 and st["queue"]["tracks"] == [track]

        # Only the active device may report state.
        phone.send_json({"type": "state", "state": {"position": 999}})

        # The phone's pause button reaches the TV.
        phone.send_json({"type": "cmd", "name": "pause", "args": []})
        assert recv_until(tv, "cmd") == {"type": "cmd", "name": "pause", "args": []}
        phone.send_json({"type": "cmd", "name": "eval", "args": ["x"]})  # unknown commands are dropped

        # Move playback to the phone: TV is told to stop, phone gets the queue and position.
        time.sleep(0.3)
        phone.send_json({"type": "transfer", "to": "phone-device-01"})
        snap = recv_until(phone, "takeover")["snapshot"]
        assert snap["queue"] == [track] and snap["index"] == 0 and snap["playing"] is True
        assert 30.2 <= snap["position"] < 32
        assert recv_until(tv, "release") == {"type": "release"}
        assert recv_until(tv, "devices")["active"] == "phone-device-01"


def test_connect_duplicate_id_is_refused(client):
    login(client)
    with client.websocket_connect("/api/connect") as a:
        hello(a, "same-device-id")
        with client.websocket_connect("/api/connect") as b:
            b.send_json({"type": "hello", "id": "same-device-id", "name": "Copy"})
            assert b.receive_json() == {"type": "duplicate"}


def test_albums_recent_sort_and_last_played(client):
    login(client)
    albums = client.get("/api/albums?sort=recent").json()
    assert all(a["lastPlayed"] is None for a in albums)
    first = next(a for a in albums if a["title"] == "First")
    track = client.get(f"/api/albums/{first['id']}").json()["tracks"][0]
    client.post(f"/api/tracks/{track['id']}/played")
    albums = client.get("/api/albums?sort=recent").json()
    assert albums[0]["title"] == "First" and albums[0]["lastPlayed"]
