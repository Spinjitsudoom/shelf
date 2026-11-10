"""Party mode: people on the server join someone's playing, add songs and vote to skip."""

from fastapi.testclient import TestClient

from shelf import party


def test_added_songs_queue_up_in_order_after_the_current_one():
    assert party.insert_at([1, 2, 3], index=0, pending=[]) == 1
    assert party.insert_at([1, 9, 2, 3], index=0, pending=[9]) == 2  # after the earlier addition
    assert party.insert_at([1, 9, 8, 2], index=0, pending=[9, 8]) == 3
    assert party.insert_at([1, 9, 2, 3], index=1, pending=[9]) == 2  # 9 is playing now: right after it
    assert party.insert_at([], index=0, pending=[]) == 0


def test_votes_need_more_than_half_of_those_present():
    p = party.Party(host=1, started=0)
    p.join(2, now=0)
    p.join(3, now=0)
    assert p.needed(now=10) == 2  # host and two guests: two of three
    assert p.vote(2, track=50, now=10) is False
    assert p.vote(2, track=50, now=10) is False  # once each
    assert p.vote(3, track=50, now=11) is True
    assert p.votes == set()  # skipped: counting starts again
    assert p.vote(2, track=51, now=12) is False
    assert p.vote(3, track=52, now=13) is False  # a new song: the old votes don't count
    assert p.needed(now=200) == 1  # the guests left the party open long ago: the host alone


def login(c, username="admin", password="hunter2"):
    assert c.post("/api/login", json={"username": username, "password": password}).status_code == 200


def recv_until(ws, kind):
    for _ in range(10):
        msg = ws.receive_json()
        if msg["type"] == kind:
            return msg
    raise AssertionError(f"no {kind} message")


def test_party(client):
    login(client)
    client.post("/api/users", json={"username": "sam", "password": "sam-pass"})
    client.post("/api/users", json={"username": "kim", "password": "kim-pass"})
    sam, kim = TestClient(client.app), TestClient(client.app)
    login(sam, "sam", "sam-pass")
    login(kim, "kim", "kim-pass")
    tracks = client.get("/api/tracks/random?limit=4").json()
    now = tracks[0]
    me = client.get("/api/session").json()["user"]["id"]

    assert sam.post(f"/api/party/{me}/join").status_code == 404  # no party yet
    with client.websocket_connect("/api/connect") as speaker:
        speaker.send_json({"type": "hello", "id": "speaker-device-01", "name": "Speaker", "kind": "speaker"})
        recv_until(speaker, "welcome")
        speaker.send_json({"type": "claim"})
        speaker.send_json({"type": "state", "state": {"index": 0, "track": now, "playing": True, "position": 5, "duration": 200},
                           "queue": {"rev": 1, "tracks": [now], "original": None}})
        assert client.post("/api/party").status_code == 200
        assert [p["host"]["username"] for p in sam.get("/api/parties").json()] == ["admin"]

        assert sam.post(f"/api/party/{me}/add", json={"trackIds": [tracks[1]["id"]]}).status_code == 403  # join first
        assert sam.post(f"/api/party/{me}/join").status_code == 200
        st = sam.get(f"/api/party/{me}").json()
        assert st["nowPlaying"]["title"] == now["title"] and st["members"] == ["admin", "sam"] and not st["isHost"]

        # Sam adds a song: it goes right after the one playing.
        assert sam.post(f"/api/party/{me}/add", json={"trackIds": [tracks[1]["id"]]}).status_code == 200
        cmd = recv_until(speaker, "cmd")
        assert cmd["name"] == "insertAt" and cmd["args"][0] == 1 and cmd["args"][1][0]["id"] == tracks[1]["id"]
        speaker.send_json({"type": "state", "state": {"index": 0, "track": now, "playing": True, "position": 9, "duration": 200},
                           "queue": {"rev": 2, "tracks": [now, tracks[1]], "original": None}})
        speaker.send_json({"type": "rename", "name": "Speaker", "kind": "speaker"})
        recv_until(speaker, "devices")  # the server has the new queue
        # Kim joins and adds one: after Sam's.
        kim.post(f"/api/party/{me}/join")
        kim.post(f"/api/party/{me}/add", json={"trackIds": [tracks[2]["id"]]})
        cmd = recv_until(speaker, "cmd")
        assert cmd["name"] == "insertAt" and cmd["args"][0] == 2

        # Three present: two votes skip.
        assert sam.post(f"/api/party/{me}/skip").json() == {"skipped": False, "votes": 1, "needed": 2}
        assert kim.post(f"/api/party/{me}/skip").json()["skipped"] is True
        assert recv_until(speaker, "cmd")["name"] == "next"

        assert sam.delete("/api/party").status_code == 404  # only the host ends it
        assert client.delete("/api/party").status_code == 200
        assert sam.get(f"/api/party/{me}").status_code == 404
