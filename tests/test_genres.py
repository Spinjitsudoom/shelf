"""Genres from MusicBrainz, per artist, alongside the files' own genre tags."""

import json

from shelf import genres, playlist_maker as pm, releases
from shelf.db import session, set_meta


def login(client):
    assert client.post("/api/login", json={"password": "hunter2"}).status_code == 200


def fake_mb(calls):
    def mb(path, **params):
        calls.append(path)
        if path == "artist":
            return {"artists": [{"id": "mb-band", "name": "Band", "score": 100}]}
        if path == "release-group":
            return {"release-groups": []}
        if path == "artist/mb-band":
            assert params.get("inc") == "genres"
            return {"genres": [{"name": "jazz", "count": 3}, {"name": "heavy metal", "count": 9},
                               {"name": "thrash metal", "count": 5}, {"name": "unloved", "count": 0}]}
        raise AssertionError(path)
    return mb


def test_daily_check_learns_artist_genres_once(client):
    db = client.app.state.cfg.db_path
    r = releases.Releases(db)
    calls = []
    r._mb = fake_mb(calls)
    r.refresh()
    assert releases.artist_genres(db)["band"] == ["heavy metal", "thrash metal", "jazz"]  # most votes first
    calls.clear()
    r.refresh()
    assert "artist/mb-band" not in calls  # known for a month


def test_song_genres_join_tags_and_artist():
    row = {"genre": "Metal; Hard-Rock / Grunge", "artist": "Band", "album_artist_name": "Band & Friends"}
    known = {"band": ["thrash metal"], "band friends": ["hard rock"]}
    assert genres.song_genres(row, known) == {"metal", "hard rock", "grunge", "thrash metal"}
    assert genres.song_genres({"genre": None, "artist": "Nobody", "album_artist_name": None}, known) == set()


def test_untagged_songs_are_found_by_their_artists_genre():
    rows = [{"id": i, "artist": a, "album_artist_name": a, "album_id": i, "genre": g, "year": 2000,
             "bpm": None, "musical_key": None, "sound": None}
            for i, (a, g) in enumerate([("Slayer", None), ("Slayer", None), ("Miles Davis", "Jazz"), ("Anthrax", "Rock")])]
    known = {"slayer": ["thrash metal"], "anthrax": ["thrash metal", "speed metal"]}
    names = genres.library_genres(rows, known)
    assert {"Thrash Metal", "Speed Metal", "Jazz", "Rock"} <= set(names)
    want = pm.understand("metal", names, [])
    of = lambda r: genres.song_genres(r, known)
    picked = pm.make(rows, {}, {}, want, lambda *a: [], size=10, seed="s", genres_of=of)
    assert sorted(picked) == [0, 1, 3]


def test_suggestions_use_artist_genres(client, library):
    from conftest import make_track
    make_track(library / "Other" / "A" / "01 Riff.mp3", title="Riff", artist="Other", album="A", track=1)
    make_track(library / "Far" / "B" / "01 Swing.mp3", title="Swing", artist="Far", album="B", track=1)
    client.app.state.scanner.run_once()
    login(client)
    db = client.app.state.cfg.db_path
    with session(db) as conn:
        conn.execute("UPDATE tracks SET genre = 'Heavy Metal' WHERE artist IN ('Band', 'band')")
        conn.execute("UPDATE tracks SET genre = NULL WHERE artist = 'Other'")
        conn.execute("UPDATE tracks SET genre = 'Jazz' WHERE artist = 'Far'")
        set_meta(conn, "mb_artist_genres", json.dumps({"other": {"genres": ["heavy metal"], "at": 0}}))
    ids = {t["title"]: t["id"] for t in client.get("/api/tracks/random?limit=20").json()}
    recs = client.post("/api/suggest", json={"trackIds": [ids["Opening"]], "exclude": [ids["Closer"], ids["Late"], ids["Early"]],
                                             "limit": 2}).json()
    assert [r["title"] for r in recs] == ["Riff", "Swing"]  # the untagged metal song first
