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


DP = "056e4f3e-d505-4dad-8ec1-d04f521cbb56"  # Daft Punk on MusicBrainz
DISCOVERY = "48117b82-8a9b-3a50-8fd7-2a4e2b0b6c7c"
HOMEWORK = "00054665-89fb-3c4a-8ec1-6a6c6b9d6c8a"


def fake_mb(calls):
    def mb(path, retries=4, **params):
        calls.append((path, params))
        if path == "artist":
            return {"artists": [
                {"id": DP, "name": "Daft Punk", "score": 100, "type": "Group", "area": {"name": "France"},
                 "life-span": {"begin": "1993"}},
                {"id": "11111111-1111-1111-1111-111111111111", "name": "Band", "score": 70, "disambiguation": "the test one"},
                {"id": "22222222-2222-2222-2222-222222222222", "name": "Daft Punk Tribute", "score": 30}]}
        if path == "release-group" and params.get("artist"):
            assert params["release-group-status"] == "website-default"  # no bootlegs
            return {"release-groups": [
                {"id": "77777777-7777-7777-7777-777777777777", "title": "Radio Interview", "primary-type": "Album",
                 "secondary-types": ["Interview"], "first-release-date": "2001-01-01"},
                {"id": HOMEWORK, "title": "Homework", "primary-type": "Album", "first-release-date": "1997-01-20"},
                {"id": "33333333-3333-3333-3333-333333333333", "title": "Alive 1997", "primary-type": "Album",
                 "secondary-types": ["Live"], "first-release-date": "2001-10-01"},
                {"id": DISCOVERY, "title": "Discovery", "primary-type": "Album", "first-release-date": "2001-03-12"}]}
        if path == "release-group":
            return {"release-groups": [
                {"id": DISCOVERY, "title": "Discovery", "primary-type": "Album", "first-release-date": "2001-03-12",
                 "score": 100, "artist-credit": [{"name": "Daft Punk", "artist": {"id": DP}}]},
                {"id": "44444444-4444-4444-4444-444444444444", "title": "First", "primary-type": "Album",
                 "score": 90, "artist-credit": [{"name": "Band", "joinphrase": " & ", "artist": {"id": "11111111-1111-1111-1111-111111111111"}},
                                                {"name": "Friend"}]},
                {"id": "55555555-5555-5555-5555-555555555555", "title": "First", "primary-type": "Album",
                 "score": 80, "artist-credit": [{"name": "Band", "artist": {"id": "11111111-1111-1111-1111-111111111111"}}]},
                {"id": "66666666-6666-6666-6666-666666666666", "title": "Noise", "score": 20, "artist-credit": []}]}
        raise AssertionError(path)
    return mb


def lookups_on(client, monkeypatch, calls):
    from shelf import releases
    monkeypatch.setattr(releases, "mb", fake_mb(calls))
    monkeypatch.setattr(wishlist, "_cache", {})
    client.app.state.cfg.artist_info = True


def test_musicbrainz_suggests_the_artist_and_album(client, monkeypatch):
    login(client)
    calls = []
    lookups_on(client, monkeypatch, calls)

    r = client.get("/api/requests/lookup", params={"kind": "artist", "q": "daft punk"}).json()["results"]
    assert [a["name"] for a in r] == ["Daft Punk", "Band"]  # weak matches left out
    assert r[0]["about"] == "Group, France, 1993" and not r[0]["onShelf"]
    assert r[1]["onShelf"]  # "Band" is in the test library
    assert calls[0][1]["query"] == "daft punk"

    # A picked artist: all their albums, studio ones first, narrowed by what's typed.
    r = client.get("/api/requests/lookup", params={"kind": "album", "artistId": DP, "artist": "Daft Punk"}).json()["results"]
    assert [a["title"] for a in r] == ["Discovery", "Homework", "Alive 1997"]
    assert r[0]["year"] == 2001 and r[2]["extra"] == "Live"
    r = client.get("/api/requests/lookup", params={"kind": "album", "artistId": DP, "q": "home"}).json()["results"]
    assert [a["title"] for a in r] == ["Homework"]
    assert sum(1 for p, _ in calls if p == "release-group") == 1  # remembered, not asked again

    # No artist picked: search albums by title.
    r = client.get("/api/requests/lookup", params={"kind": "album", "q": "disc(overy"}).json()["results"]
    assert r[0]["artist"] == "Daft Punk" and r[0]["artistId"] == DP
    assert r[1]["artist"] == "Band & Friend" and not r[1]["onShelf"]  # their album together isn't Band's own
    assert r[2]["artist"] == "Band" and r[2]["onShelf"]  # "First" by Band is on the shelf
    assert len(r) == 3  # weak matches left out
    assert calls[-1][1]["query"] == r"releasegroup:(disc\(overy) AND (primarytype:album OR primarytype:ep)"


def test_a_picked_album_is_remembered_and_matched_by_its_id(client, monkeypatch):
    login(client)
    body = {"artist": "Daft Punk", "album": "Discovery", "artistId": DP, "albumId": DISCOVERY, "year": 2001, "type": "Album"}
    made = client.post("/api/requests", json=body).json()
    assert (made["artistId"], made["albumId"], made["year"], made["type"]) == (DP, DISCOVERY, 2001, "Album")
    # Same album under another spelling is the same request.
    sam = add_user(client)
    r = sam.post("/api/requests", json={**body, "album": "Discovery (Deluxe)"})
    assert r.status_code == 409
    assert client.post("/api/requests", json={**body, "albumId": "not-an-id"}).status_code == 422


def test_an_edition_on_the_shelf_answers_the_request(client):
    login(client)
    client.post("/api/requests", json={"artist": "Band", "album": "Third"})
    with session(client.app.state.cfg.db_path) as conn:
        conn.execute("""INSERT INTO albums(key, title, artist, track_count, duration, added_at)
                        VALUES('band|third', 'Third (Deluxe Edition)', 'Band', 1, 60, 1)""")
        assert [r["album"] for r in wishlist.fulfil(conn)] == ["Third"]
    r = client.post("/api/requests", json={"artist": "band", "album": "Third [Remastered]"})
    assert r.status_code == 409 and "already on the shelf" in r.json()["detail"]


def test_lookups_off_or_unreachable(client, monkeypatch):
    login(client)
    assert client.get("/api/requests/lookup", params={"kind": "artist", "q": "daft"}).json()["off"]
    assert client.get("/api/requests").json()["lookup"] is False

    def down(*a, **k):
        raise OSError("no network")
    from shelf import releases
    monkeypatch.setattr(releases, "mb", down)
    monkeypatch.setattr(wishlist, "_cache", {})
    client.app.state.cfg.artist_info = True
    r = client.get("/api/requests/lookup", params={"kind": "artist", "q": "daft"}).json()
    assert r["results"] == [] and "type it in yourself" in r["error"]
