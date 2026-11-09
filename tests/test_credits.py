import sqlite3

from fastapi.testclient import TestClient

from shelf import credits
from shelf.app import create_app
from shelf.config import Config

from conftest import make_track


def _library(*credits_):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE tracks (artist TEXT)")
    conn.execute("CREATE TABLE albums (artist TEXT, track_count INTEGER)")
    for c in credits_:
        conn.execute("INSERT INTO tracks VALUES (?)", (c,))
        conn.execute("INSERT INTO albums VALUES (?, 1)", (c,))
    credits.refresh(conn)


def test_shared_credits_split_when_an_artist_is_known():
    _library("YUNGBLUD", "YUNGBLUD", "Måneskin", "Aerosmith & Yungblud", "Earth, Wind & Fire", "Simon & Garfunkel")
    assert credits.names("Aerosmith & Yungblud") == ["Aerosmith", "YUNGBLUD"]  # the library's spelling
    assert credits.names("YUNGBLUD, Halsey") == ["YUNGBLUD", "Halsey"]
    assert credits.names("Måneskin, ELVIS (Original Motion Picture Soundtrack)") == ["Måneskin"]
    assert credits.names("Earth, Wind & Fire") == ["Earth, Wind & Fire"]  # nobody in it is known alone
    assert credits.names("Simon & Garfunkel") == ["Simon & Garfunkel"]
    assert credits.names("Lil Nas X") == ["Lil Nas X"]
    assert credits.names("Someone feat. Other") == ["Someone", "Other"]  # "feat." always means two
    assert credits.credited("Aerosmith & Yungblud", "yungblud")
    assert not credits.credited("Aerosmith & Yungblud", "Halsey")


def test_shared_album_shows_on_each_artists_page(tmp_path):
    root = tmp_path / "music"
    make_track(root / "Solo" / "Alone" / "01 One.mp3", title="One", artist="Solo", album="Alone", track=1)
    make_track(root / "Duet" / "Together" / "01 Two.mp3", title="Two", artist="Partner, Solo",
               album="Together", album_artist="Partner & Solo", track=1)
    make_track(root / "Other" / "Guests" / "01 Three.mp3", title="Three", artist="Other, Guest",
               album="Guests", album_artist="Other", track=1)
    make_track(root / "Other" / "Guests" / "02 Four.mp3", title="Four", artist="Other",
               album="Guests", album_artist="Other", track=2)
    cfg = Config(music_dirs=[root], data_dir=tmp_path / "data", password="hunter2", online_lyrics=False,
                 music_videos=False, artist_info=False, analyze_tempo=False)
    app = create_app(cfg, start_scanner=False)
    app.state.scanner.run_once()
    with TestClient(app) as c:
        assert c.post("/api/login", json={"password": "hunter2"}).status_code == 200
        names = {a["name"]: a["albums"] for a in c.get("/api/artists").json()}
        assert names == {"Solo": 2, "Partner": 1, "Other": 1}  # no "Partner & Solo"
        solo = c.get("/api/artist?name=Solo").json()
        assert {a["title"] for a in solo["albums"]} == {"Alone", "Together"}
        partner = c.get("/api/artist?name=Partner").json()
        assert [a["title"] for a in partner["albums"]] == ["Together"]
        guest = c.get("/api/artist?name=Guest").json()  # a feature: on someone else's album
        assert [t["title"] for t in guest["popular"]] == ["Three"] and [a["title"] for a in guest["appearsOn"]] == ["Guests"]
        album = next(a for a in c.get("/api/albums").json() if a["title"] == "Together")
        assert album["artist"] == "Partner & Solo" and album["artists"] == ["Partner", "Solo"]
        assert {a["title"] for a in c.get("/api/albums?artist=solo").json()} == {"Alone", "Together"}
        assert {t["title"] for t in c.get("/api/tracks/random?artist=Solo").json()} == {"One", "Two"}
        assert [a["name"] for a in c.get("/api/search?q=part").json()["artists"]] == ["Partner"]
