"""Suggestions from songs that appear together (playlists, listening sessions), and "sounds like"
measured against each song rather than the average."""

import numpy as np

from shelf import sound, together
from shelf.db import session


def test_sessions_break_after_half_an_hour():
    plays = [(1, 10, 0), (1, 11, 600), (1, 12, 600 + 1801), (2, 13, 700), (2, 14, 900)]
    assert sorted(map(sorted, together.sessions(plays))) == [[10, 11], [12], [13, 14]]


def test_together_scores():
    playlists = [[1, 2, 3, 8, 9], [1, 4]]
    sessions = [[1, 5], [6, 7]]
    s = together.scores(playlists, sessions, {1})
    assert s[4] > s[2] > 0  # a small playlist says more than a big one
    assert s[5] > 0 and 6 not in s and 7 not in s and 1 not in s
    assert max(s.values()) == 1.0


def test_nearest_beats_the_average():
    unit = lambda v: np.array(v, dtype=float) / np.linalg.norm(v)
    vecs = {1: unit([1, 0]), 2: unit([0, 1]), 3: unit([0.95, 0.05]), 4: unit([0.7, 0.7])}
    near = sound.nearest(vecs, [1, 2], [3, 4])
    assert near[3] > near[4]  # like one of the songs, not like their muddy middle
    assert sound.nearest(vecs, [], [3]) == {}


def test_playlist_suggestions_follow_songs_that_share_playlists(client):
    assert client.post("/api/login", json={"password": "hunter2"}).status_code == 200
    db = client.app.state.cfg.db_path
    with session(db) as conn:
        conn.execute("UPDATE tracks SET genre = 'Rock', bpm = 120, musical_key = 'A minor'")
    ids = {t["title"]: t["id"] for t in client.get("/api/tracks/random?limit=10").json()}
    client.post("/api/playlists", json={"name": "Road trip", "trackIds": [ids["Opening"], ids["Late"]]})
    p = client.post("/api/playlists", json={"name": "New", "trackIds": [ids["Opening"]]}).json()
    recs = [r["title"] for r in client.get(f"/api/playlists/{p['id']}/recommendations").json()]
    assert recs[0] == "Late"  # it shares a playlist with Opening
