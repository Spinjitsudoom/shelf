"""Library health: what's missing or wrong on the shelf, and finding covers for albums without one."""

import io
import json

from fastapi.testclient import TestClient
from PIL import Image

from shelf import coverfix, health, scanner
from shelf.db import init_db, session


def add_album(conn, key, title, artist, cover=None, year=None):
    conn.execute("INSERT INTO albums(key, title, artist, year, track_count, duration, cover_src, added_at)"
                 " VALUES(?, ?, ?, ?, 0, 0, ?, 0)", (key, title, artist, year, cover))
    return conn.execute("SELECT id FROM albums WHERE key = ?", (key,)).fetchone()[0]


def add_track(conn, key, title, artist="Band", no=None, disc=None, dur=200.0, codec="mp3", bitrate=320000, year=None, path=None):
    path = path or f"/music/{key}/{title}-{no}-{disc}.{codec}"
    conn.execute("INSERT INTO tracks(path, mtime, size, title, artist, album, album_key, track_no, disc_no, duration,"
                 " codec, bitrate, year, added_at) VALUES(?, 0, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
                 (path, title, artist, key, key, no, disc, dur, codec, bitrate, year))


def db(tmp_path):
    p = tmp_path / "library.db"
    init_db(p)
    return p


def run(path, dims=None, unreadable=()):
    with session(path) as conn:
        return health.report(conn, dims or (lambda src: None), list(unreadable))


def test_covers_missing_or_too_small(tmp_path):
    p = db(tmp_path)
    with session(p) as conn:
        add_album(conn, "a", "No Art", "Band")
        add_album(conn, "b", "Tiny Art", "Band", cover="file:/tiny.jpg")
        add_album(conn, "c", "Fine Art", "Band", cover="file:/big.jpg")
    r = run(p, dims=lambda src: {"file:/tiny.jpg": (300, 300), "file:/big.jpg": (1200, 1200)}[src])
    assert [a["title"] for a in r["noCover"]] == ["No Art"]
    assert [(a["title"], a["size"]) for a in r["smallCover"]] == [("Tiny Art", [300, 300])]


def test_gaps_in_track_numbers(tmp_path):
    p = db(tmp_path)
    with session(p) as conn:
        add_album(conn, "a", "Holes", "Band")
        for no in (1, 2, 4):
            add_track(conn, "a", f"S{no}", no=no, disc=1)
        for no in (1, 2):
            add_track(conn, "a", f"T{no}", no=no, disc=2)
        add_album(conn, "b", "Unnumbered", "Band")
        add_track(conn, "b", "X")
        add_track(conn, "b", "Y")
    gaps = run(p)["gaps"]
    assert [(g["title"], g["disc"], g["missing"]) for g in gaps] == [("Holes", 1, [3])]


def test_the_same_song_twice_keeps_the_best_copy(tmp_path):
    p = db(tmp_path)
    with session(p) as conn:
        add_album(conn, "a", "Album", "Band")
        add_album(conn, "b", "Greatest Hits", "Band")
        add_track(conn, "a", "Hit", dur=200, codec="mp3", bitrate=192000)
        add_track(conn, "b", "Hit", dur=201, codec="flac", bitrate=900000)
        add_track(conn, "b", "Hit", dur=260, codec="flac", path="/music/b/Hit (Live).flac")  # a different take
        add_track(conn, "a", "Other")
    dups = run(p)["duplicates"]
    assert len(dups) == 1 and len(dups[0]["copies"]) == 2
    best = next(c for c in dups[0]["copies"] if c["id"] == dups[0]["best"])
    assert best["codec"] == "flac" and best["album"] == "Greatest Hits"


def test_tags_and_unreadable_files(tmp_path):
    p = db(tmp_path)
    with session(p) as conn:
        add_album(conn, "a", "Mixed", "Band")
        add_track(conn, "a", "One", year=1999)
        add_track(conn, "a", "Two", year=2003)
        add_album(conn, "b", "Nobody", "Unknown Artist")
        add_track(conn, "b", "Mystery", artist="Unknown Artist")
    r = run(p, unreadable=["/music/broken.mp3"])
    assert [(m["title"], m["years"]) for m in r["mixedYears"]] == [("Mixed", [1999, 2003])]
    assert [t["title"] for t in r["noArtist"]] == ["Mystery"]
    assert r["unreadable"] == ["/music/broken.mp3"]
    assert r["counts"]["mixedYears"] == 1 and r["counts"]["noArtist"] == 1


# ---------- finding covers ----------

def jpeg(size=1200):
    out = io.BytesIO()
    Image.new("RGB", (size, size), (200, 30, 30)).save(out, "JPEG")
    return out.getvalue()


class FakeWeb:
    def __init__(self):
        self.urls = []

    def __call__(self, url, timeout=20):
        self.urls.append(url)
        if "musicbrainz.org" in url:
            return json.dumps({"release-groups": [
                {"id": "11111111-1111-1111-1111-111111111111", "score": 100, "title": "Second",
                 "first-release-date": "2001-05-01", "artist-credit": [{"name": "band"}], "primary-type": "Album"},
                {"id": "22222222-2222-2222-2222-222222222222", "score": 60, "title": "Second Thoughts",
                 "artist-credit": [{"name": "Someone Else"}]},
            ]}).encode()
        if "coverartarchive.org" in url:
            return jpeg()
        raise AssertionError(url)


def test_candidates_and_a_strict_match():
    web = FakeWeb()
    found = coverfix.candidates("band", "Second", get=web)
    assert [c["mbid"][:4] for c in found] == ["1111", "2222"] and found[0]["year"] == 2001
    assert coverfix.good_match("band", "Second (Deluxe Edition)", found[0])
    assert not coverfix.good_match("band", "Second", found[1])


def login(c):
    assert c.post("/api/login", json={"username": "admin", "password": "hunter2"}).status_code == 200


def test_admin_report_and_cover_fixing(client, monkeypatch):
    web = FakeWeb()
    monkeypatch.setattr(coverfix, "_get", web)
    login(client)
    r = client.get("/api/admin/health").json()
    second = next(a for a in r["noCover"] if a["title"] == "Second")

    cands = client.get(f"/api/admin/covers/{second['id']}/candidates").json()
    assert cands[0]["mbid"].startswith("1111") and cands[0]["image"]
    assert client.post(f"/api/admin/covers/{second['id']}", json={"mbid": cands[0]["mbid"]}).status_code == 200
    assert client.get(f"/api/albums/{second['id']}/cover?size=100").status_code == 200
    assert "Second" not in [a["title"] for a in client.get("/api/admin/health").json()["noCover"]]

    # A rescan keeps the found cover; taking it away goes back to the album's own (none here).
    client.app.state.scanner.run_once()
    album = next(a for a in client.get("/api/albums").json() if a["title"] == "Second")
    assert album["cover"]
    assert client.delete(f"/api/admin/covers/{album['id']}").status_code == 200
    assert client.get(f"/api/albums/{album['id']}/cover?size=100").status_code == 404


def test_find_all_missing_covers(client, monkeypatch):
    web = FakeWeb()
    monkeypatch.setattr(coverfix, "_get", web)
    monkeypatch.setattr(coverfix, "PAUSE", 0)
    login(client)
    assert client.post("/api/admin/covers/find-missing").json()["running"] is True
    client.app.state.cover_finder.wait()
    state = client.get("/api/admin/health").json()["finder"]
    assert state["found"] == 1 and state["done"] == 1 and not state["running"]
    assert client.get("/api/admin/health").json()["noCover"] == []


def test_health_is_admin_only(client):
    login(client)
    client.post("/api/users", json={"username": "sam", "password": "sam-pass"})
    sam = TestClient(client.app)
    assert sam.post("/api/login", json={"username": "sam", "password": "sam-pass"}).status_code == 200
    assert sam.get("/api/admin/health").status_code == 403
    assert sam.post("/api/admin/covers/find-missing").status_code == 403


def test_found_cover_wins_in_the_scanner(tmp_path):
    found = tmp_path / "found"
    found.mkdir()
    key = "/music/a\x1fa"
    coverfix.override_path(found, key).write_bytes(jpeg(600))
    rows = [{"path": "/music/a/1.mp3", "has_art": 1}]
    assert scanner._pick_cover(rows, found, key) == f"file:{coverfix.override_path(found, key)}"
    assert scanner._pick_cover(rows, found, "other") == "embedded:/music/a/1.mp3"
