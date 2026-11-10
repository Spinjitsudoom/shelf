from fastapi.testclient import TestClient


def login(client, username="admin", password="hunter2"):
    r = client.post("/api/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text


def two(client):
    login(client)
    client.post("/api/users", json={"username": "sam", "password": "sam-pass"})
    other = TestClient(client.app)
    login(other, "sam", "sam-pass")
    return other


def test_sharing_a_playlist(client):
    sam = two(client)
    tracks = [t["id"] for t in client.get("/api/tracks/random?limit=4").json()]
    pid = client.post("/api/playlists", json={"name": "Road trip", "trackIds": tracks[:2]}).json()["id"]
    assert sam.get(f"/api/playlists/{pid}").status_code == 404  # private

    client.patch(f"/api/playlists/{pid}", json={"shared": 1})
    p = sam.get(f"/api/playlists/{pid}").json()
    assert p["mine"] is False and p["canEdit"] is False and p["owner"]["username"] == "admin"
    assert sam.post(f"/api/playlists/{pid}/tracks", json={"trackIds": [tracks[2]]}).status_code == 403
    assert sam.patch(f"/api/playlists/{pid}", json={"name": "Mine now"}).status_code == 403
    assert [x["id"] for x in sam.get("/api/playlists-shared").json()] == [pid]

    client.patch(f"/api/playlists/{pid}", json={"shared": 2})
    assert sam.post(f"/api/playlists/{pid}/tracks", json={"trackIds": [tracks[2]]}).status_code == 200
    assert client.get(f"/api/playlists/{pid}").json()["tracks"][-1]["addedBy"] == "sam"
    assert sam.delete(f"/api/playlists/{pid}").status_code == 403  # only the owner deletes

    assert sam.put(f"/api/playlists/{pid}/follow").json()["following"] is True
    assert pid in [x["id"] for x in sam.get("/api/playlists").json()]
    assert client.get(f"/api/playlists/{pid}").json()["followers"] == 1

    client.patch(f"/api/playlists/{pid}", json={"shared": 0})  # private again
    assert pid not in [x["id"] for x in sam.get("/api/playlists").json()]
    assert sam.get(f"/api/playlists/{pid}").status_code == 404


def test_friend_activity_and_privacy(client):
    sam = two(client)
    tid = client.get("/api/tracks/random?limit=1").json()[0]["id"]
    client.post(f"/api/tracks/{tid}/played")
    act = sam.get("/api/activity").json()
    assert act[0]["user"]["username"] == "admin" and act[0]["last"]["track"]["id"] == tid
    assert client.patch("/api/me", json={"shareActivity": False}).json()["shareActivity"] is False
    assert sam.get("/api/activity").json() == []
    assert sam.get(f"/api/blend/1").status_code == 403


def test_blend(client):
    sam = two(client)
    ids = [t["id"] for t in client.get("/api/tracks/random?limit=4").json()]
    for t in ids[:3]:
        client.post(f"/api/tracks/{t}/played")
    for t in ids[1:]:
        sam.post(f"/api/tracks/{t}/played")
    b = sam.get("/api/blend/1").json()
    assert b["name"] == "admin + sam" and 0 < b["match"] <= 100
    assert client.get(f"/api/blend/{sam.get('/api/session').json()['user']['id']}").json()["match"] is not None
    assert {t["blendFor"] for t in b["tracks"]} <= {"you", "them", "both"} and b["tracks"]
    people = sam.get("/api/people").json()
    assert people == [{"id": 1, "username": "admin", "canBlend": True}]


def test_listenbrainz_scrobbling(client, monkeypatch):
    from shelf import scrobble
    sent = []
    monkeypatch.setattr(scrobble, "check_token", lambda tok: "listener_lb" if tok == "good" else (_ for _ in ()).throw(ValueError("nope")))
    monkeypatch.setattr(scrobble, "_call", lambda path, token, body=None, timeout=15: sent.append((path, token, body)) or {})
    login(client)
    assert client.patch("/api/me", json={"listenbrainzToken": "bad"}).status_code == 400
    assert client.patch("/api/me", json={"listenbrainzToken": "good"}).json()["listenbrainz"] == "listener_lb"
    tid = client.get("/api/tracks/random?limit=1").json()[0]["id"]
    client.post(f"/api/tracks/{tid}/played?at=1700000000")
    assert scrobble.Scrobbler(client.app.state.cfg.db_path).flush() == 1
    path, token, body = sent[-1]
    assert path == "submit-listens" and token == "good"
    assert body["payload"][0]["listened_at"] == 1700000000 or body["payload"][0]["listened_at"] > 0
    assert client.patch("/api/me", json={"listenbrainzToken": ""}).json()["listenbrainz"] is None


def test_artist_play_counts_are_everyones(client):
    """Plays on an artist page add up everyone's, including people who keep their listening private
    (a total says nothing about who played what)."""
    sam = two(client)
    tracks = {t["title"]: t["id"] for t in client.get("/api/tracks/random?limit=10").json()}
    closer = tracks["Closer"]
    for _ in range(2):
        client.post(f"/api/tracks/{closer}/played")
    for _ in range(3):
        sam.post(f"/api/tracks/{closer}/played")

    page = client.get("/api/artist?name=Band").json()
    song = next(t for t in page["popular"] if t["title"] == "Closer")
    assert song["plays"] == 5 and page["stats"]["plays"] == 5
    album = next(a for a in page["albums"] if a["title"] == "First")
    assert album["plays"] == 5
    assert sam.get("/api/artist?name=Band").json()["stats"]["plays"] == 5  # the same for everyone

    sam.patch("/api/me", json={"shareActivity": False})
    assert client.get("/api/artist?name=Band").json()["stats"]["plays"] == 5  # still counted
