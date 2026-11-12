"""Requests: ask for an artist or an album; admins resolve them, and a scan that brings the
music marks them done by itself."""

from fastapi.testclient import TestClient

from shelf.db import session
from shelf import requests as wishlist


def login(c, username="admin", password="hunter2"):
    assert c.post("/api/login", json={"username": username, "password": password}).status_code == 200


def add_user(client, name="sam", password="sam-pass"):
    client.post("/api/users", json={"username": name, "password": password})
    other = TestClient(client.app)
    login(other, name, password)
    return other


def test_asking_and_seeing_everyones(client):
    login(client)
    sam = add_user(client)
    r = sam.post("/api/requests", json={"artist": "Daft Punk", "album": "Discovery", "note": "the 2001 one"})
    assert r.status_code == 200
    made = r.json()
    assert made["artist"] == "Daft Punk" and made["album"] == "Discovery" and made["status"] == "open"
    assert made["requestedBy"] == "sam" and made["mine"]
    sam.post("/api/requests", json={"artist": "Burial"})

    # The whole household sees the list; "mine" marks your own.
    theirs = client.get("/api/requests").json()["requests"]
    assert [x["artist"] for x in theirs] == ["Burial", "Daft Punk"]
    assert all(x["requestedBy"] == "sam" and not x["mine"] for x in theirs)
    assert sam.get("/api/requests").json()["requests"][0]["mine"]


def test_whats_already_on_the_shelf_and_asked_twice(client):
    login(client)
    # The test library has the album "First" by "Band".
    r = client.post("/api/requests", json={"artist": "band"})
    assert r.status_code == 409 and "already on the shelf" in r.json()["detail"]
    r = client.post("/api/requests", json={"artist": "BAND", "album": "first"})
    assert r.status_code == 409
    # An album they don't have yet is a fine request, even for a known artist.
    assert client.post("/api/requests", json={"artist": "Band", "album": "Third"}).status_code == 200

    sam = add_user(client)
    r = sam.post("/api/requests", json={"artist": "band", "album": "THIRD "})
    assert r.status_code == 409 and "admin" in r.json()["detail"]
    r = client.post("/api/requests", json={"artist": "Band", "album": "Third"})
    assert r.status_code == 409 and "You" in r.json()["detail"]
    assert client.post("/api/requests", json={"artist": "   "}).status_code in (400, 422)


def test_resolving_is_the_admins_withdrawing_is_yours(client):
    login(client)
    sam = add_user(client)
    rid = sam.post("/api/requests", json={"artist": "Burial"}).json()["id"]
    other = sam.post("/api/requests", json={"artist": "Aphex Twin"}).json()["id"]

    # Only an admin marks things done or declined.
    assert sam.patch(f"/api/requests/{rid}", json={"status": "done"}).status_code == 403
    done = client.patch(f"/api/requests/{rid}", json={"status": "done"})
    assert done.status_code == 200 and done.json()["status"] == "done" and done.json()["resolvedAt"]
    reopened = client.patch(f"/api/requests/{rid}", json={"status": "open"}).json()
    assert reopened["status"] == "open" and reopened["resolvedAt"] is None

    # You can withdraw your own; you can't withdraw someone else's, but an admin can.
    mine = client.post("/api/requests", json={"artist": "Boards of Canada"}).json()["id"]
    assert sam.delete(f"/api/requests/{mine}").status_code == 404
    assert client.delete(f"/api/requests/{mine}").status_code == 200
    assert sam.delete(f"/api/requests/{other}").status_code == 200
    assert client.delete(f"/api/requests/{rid}").status_code == 200
    assert client.get("/api/requests").json()["requests"] == []
    assert client.patch("/api/requests/999", json={"status": "done"}).status_code == 404


def test_a_scan_that_brings_the_music_marks_it_done(client):
    login(client)
    client.post("/api/requests", json={"artist": "The Knife", "album": "Silent Shout"})
    client.post("/api/requests", json={"artist": "Band", "album": "Third"})
    client.post("/api/requests", json={"artist": "New Act"})

    with session(client.app.state.cfg.db_path) as conn:
        # Nothing matching yet: everything stays open.
        assert wishlist.fulfil(conn) == []
        conn.execute("""INSERT INTO albums(key, title, artist, track_count, duration, added_at)
                        VALUES('band|third', 'Third', 'Band', 1, 60, 1)""")
        conn.execute("""INSERT INTO albums(key, title, artist, track_count, duration, added_at)
                        VALUES('new act|hello', 'Hello', 'New Act', 1, 60, 1)""")
        got = wishlist.fulfil(conn)
    assert sorted(r["artist"] for r in got) == ["Band", "New Act"]

    byArtist = {x["artist"]: x for x in client.get("/api/requests").json()["requests"]}
    assert byArtist["Band"]["status"] == "done" and byArtist["Band"]["resolvedAt"]
    assert byArtist["New Act"]["status"] == "done"
    assert byArtist["The Knife"]["status"] == "open"
