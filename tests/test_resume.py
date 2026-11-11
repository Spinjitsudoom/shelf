"""Long tracks (live sets, DJ mixes, audiobooks) pick up where each person stopped."""

from fastapi.testclient import TestClient

from shelf.db import session
from test_subsonic import Sub, app_password, login


def long_track(client, minutes=60):
    with session(client.app.state.cfg.db_path) as conn:
        tid = conn.execute("SELECT id FROM tracks ORDER BY id LIMIT 1").fetchone()[0]
        conn.execute("UPDATE tracks SET duration = ? WHERE id = ?", (minutes * 60.0, tid))
    return tid


def test_where_you_stopped_is_kept(client):
    login(client)
    tid = long_track(client)
    assert client.get(f"/api/tracks/{tid}/resume").json() == {"position": 0}
    assert client.put(f"/api/tracks/{tid}/resume", json={"position": 1234.5}).status_code == 200
    assert client.get(f"/api/tracks/{tid}/resume").json() == {"position": 1234.5}
    # Each person has their own place.
    client.post("/api/users", json={"username": "sam", "password": "sam-pass"})
    sam = TestClient(client.app)
    sam.post("/api/login", json={"username": "sam", "password": "sam-pass"})
    assert sam.get(f"/api/tracks/{tid}/resume").json() == {"position": 0}


def test_the_start_or_the_end_forgets_it(client):
    login(client)
    tid = long_track(client)
    client.put(f"/api/tracks/{tid}/resume", json={"position": 600})
    client.put(f"/api/tracks/{tid}/resume", json={"position": 3600 - 10})  # the last half minute: finished
    assert client.get(f"/api/tracks/{tid}/resume").json() == {"position": 0}
    client.put(f"/api/tracks/{tid}/resume", json={"position": 600})
    client.put(f"/api/tracks/{tid}/resume", json={"position": 3})  # back at the start
    assert client.get(f"/api/tracks/{tid}/resume").json() == {"position": 0}
    assert client.put("/api/tracks/999999/resume", json={"position": 600}).status_code == 404


def test_subsonic_bookmarks_are_the_same_places(client):
    login(client)
    tid = long_track(client)
    sub = Sub(client, app_password(client))
    sub.ok("createBookmark", id=str(tid), position="754000")  # milliseconds
    assert client.get(f"/api/tracks/{tid}/resume").json() == {"position": 754.0}
    marks = sub.ok("getBookmarks")["bookmarks"]["bookmark"]
    assert len(marks) == 1 and marks[0]["position"] == 754000 and marks[0]["entry"]["id"] == str(tid)
    sub.ok("deleteBookmark", id=str(tid))
    assert sub.ok("getBookmarks")["bookmarks"] == {}
