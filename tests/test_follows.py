"""Following artists: each person's own list, marked on the artists and the artist page, and
the same thing as a star on the artist in a Subsonic app."""

from fastapi.testclient import TestClient


def login(c, username="admin", password="hunter2"):
    assert c.post("/api/login", json={"username": username, "password": password}).status_code == 200


def following(c):
    return {a["name"] for a in c.get("/api/artists").json() if a["following"]}


def test_follow_and_unfollow_an_artist(client):
    login(client)
    assert following(client) == set()
    assert client.get("/api/artist", params={"name": "Band"}).json()["following"] is False

    # Case and accents don't matter; it's the same artist.
    r = client.put("/api/artist/follow", params={"name": "band"})
    assert r.status_code == 200 and r.json() == {"following": True}
    assert following(client) == {"Band"}
    assert client.get("/api/artist", params={"name": "Band"}).json()["following"] is True
    assert client.put("/api/artist/follow", params={"name": "Band"}).status_code == 200  # twice is fine

    assert client.delete("/api/artist/follow", params={"name": "BAND"}).json() == {"following": False}
    assert following(client) == set()


def test_follows_are_each_persons_own(client):
    login(client)
    client.post("/api/users", json={"username": "sam", "password": "sam-pass"})
    sam = TestClient(client.app)
    login(sam, "sam", "sam-pass")
    client.put("/api/artist/follow", params={"name": "Band"})
    assert following(client) == {"Band"}
    assert following(sam) == set()


def test_a_follow_is_a_subsonic_star(client):
    login(client)
    client.put("/api/artist/follow", params={"name": "Band"})
    auth = {"u": "admin", "p": "hunter2", "v": "1.16.1", "c": "test", "f": "json"}
    starred = client.get("/rest/getStarred2", params=auth).json()["subsonic-response"]["starred2"]
    assert [a["name"] for a in starred.get("artist", [])] == ["Band"]

    # Unstarring in the app unfollows in Shelf.
    artist_id = starred["artist"][0]["id"]
    client.get("/rest/unstar", params={**auth, "artistId": artist_id})
    assert following(client) == set()
