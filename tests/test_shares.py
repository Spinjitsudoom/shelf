"""Share links: a song, an album or a playlist anyone with the link can listen to, without an account."""

import time

from fastapi.testclient import TestClient

from shelf.db import session


def login(c, username="admin", password="hunter2"):
    assert c.post("/api/login", json={"username": username, "password": password}).status_code == 200


def first_album(client):
    a = client.get("/api/albums").json()[0]
    return a, client.get(f"/api/albums/{a['id']}").json()["tracks"]


def turn_on(client):
    assert client.patch("/api/admin/shares", json={"enabled": True}).status_code == 200


def test_off_until_an_admin_turns_them_on(client):
    login(client)
    a, _ = first_album(client)
    r = client.post("/api/shares", json={"kind": "album", "id": a["id"]})
    assert r.status_code == 403 and "admin" in r.json()["detail"]
    turn_on(client)
    assert client.post("/api/shares", json={"kind": "album", "id": a["id"]}).status_code == 200


def test_anyone_with_the_link_listens_to_just_that(client):
    login(client)
    turn_on(client)
    a, tracks = first_album(client)
    share = client.post("/api/shares", json={"kind": "album", "id": a["id"], "days": 7}).json()
    assert share["path"] == f"/s/{share['token']}" and len(share["token"]) >= 16
    assert share["expiresAt"] > time.time() + 6 * 86400

    guest = TestClient(client.app)  # no account
    page = guest.get(share["path"])
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    info = guest.get(f"{share['path']}/info").json()
    assert info["title"] == a["title"] and info["by"] == a["artist"] and info["sharedBy"] == "admin"
    assert [t["id"] for t in info["tracks"]] == [t["id"] for t in tracks]
    assert "path" not in info["tracks"][0]  # nothing about the server's folders
    assert guest.get(f"{share['path']}/tracks/{tracks[0]['id']}/stream").status_code == 200
    # Only what was shared: another album's song, or the rest of the API, stays closed.
    other = next(t for x in client.get("/api/albums").json()[1:] for t in client.get(f"/api/albums/{x['id']}").json()["tracks"])
    assert guest.get(f"{share['path']}/tracks/{other['id']}/stream").status_code == 404
    assert guest.get("/api/albums").status_code == 401
    assert guest.get("/s/not-a-real-link/info").status_code == 404


def test_stopping_expiry_and_switching_off(client):
    login(client)
    turn_on(client)
    a, tracks = first_album(client)
    one = client.post("/api/shares", json={"kind": "track", "id": tracks[0]["id"], "days": None}).json()
    assert one["expiresAt"] is None
    two = client.post("/api/shares", json={"kind": "album", "id": a["id"], "days": 1}).json()
    guest = TestClient(client.app)
    assert [s["token"] for s in client.get("/api/shares").json()] == [two["token"], one["token"]]

    assert client.delete(f"/api/shares/{one['token']}").status_code == 200
    assert guest.get(f"{one['path']}/info").status_code == 404

    with session(client.app.state.cfg.db_path) as conn:
        conn.execute("UPDATE shares SET expires_at = ? WHERE token = ?", (time.time() - 1, two["token"]))
    r = guest.get(f"{two['path']}/info")
    assert r.status_code == 410 and "expired" in r.json()["detail"]

    three = client.post("/api/shares", json={"kind": "album", "id": a["id"]}).json()
    assert client.patch("/api/admin/shares", json={"enabled": False}).status_code == 200
    assert guest.get(f"{three['path']}/info").status_code == 404
    assert client.post("/api/shares", json={"kind": "album", "id": a["id"], "days": 7}).status_code == 403


def test_playlists_and_whose_links(client):
    login(client)
    turn_on(client)
    _, tracks = first_album(client)
    pl = client.post("/api/playlists", json={"name": "Road trip"}).json()
    client.post(f"/api/playlists/{pl['id']}/tracks", json={"trackIds": [tracks[0]["id"]]})
    share = client.post("/api/shares", json={"kind": "playlist", "id": pl["id"]}).json()
    guest = TestClient(client.app)
    info = guest.get(f"{share['path']}/info").json()
    assert info["title"] == "Road trip" and [t["id"] for t in info["tracks"]] == [tracks[0]["id"]]

    # Someone else can't share a private playlist of yours, or stop your links.
    client.post("/api/users", json={"username": "sam", "password": "sam-pass"})
    sam = TestClient(client.app)
    login(sam, "sam", "sam-pass")
    assert sam.post("/api/shares", json={"kind": "playlist", "id": pl["id"]}).status_code in (403, 404)
    assert sam.delete(f"/api/shares/{share['token']}").status_code == 404
    assert sam.get("/api/shares").json() == []
    assert client.post("/api/shares", json={"kind": "album", "id": 999999}).status_code == 404
    assert client.post("/api/shares", json={"kind": "album", "id": tracks[0]["albumId"], "days": 12}).status_code == 422
