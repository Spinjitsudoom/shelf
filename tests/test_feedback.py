"""Suggestions learn from what someone skips, and from suggestions they take back out."""

from shelf import feedback
from shelf.db import session

DAY = 86400


def test_penalties():
    now = 1000 * DAY
    rows = [
        (1, "band", "skip", None, now - DAY),
        (2, "band", "skip", None, now - DAY), (2, "band", "skip", None, now - DAY), (2, "band", "skip", None, now - DAY),
        (2, "band", "skip", None, now - DAY),
        (3, "band", "removed", 7, now - DAY),
        (4, "other", "skip", None, now - 100 * DAY),  # long ago: forgotten
    ]
    song, artist, banned = feedback.penalties(rows, now, playlist_id=7)
    assert round(song[1], 2) == 0.67 and song[2] == 2.0 and round(song[3], 2) == 1.33  # skips add up, to a limit
    assert 4 not in song
    assert artist == {"band": 1.0}  # three of their songs turned down
    assert banned == {3}  # taken back out of this playlist: never suggested for it again
    assert feedback.penalties(rows, now, playlist_id=8)[2] == set()


def login(client):
    assert client.post("/api/login", json={"password": "hunter2"}).status_code == 200


def test_skips_and_removed_suggestions_count(client):
    login(client)
    with session(client.app.state.cfg.db_path) as conn:
        conn.execute("UPDATE tracks SET genre = 'Rock', bpm = 120, musical_key = 'A minor'")
    ids = {t["title"]: t["id"] for t in client.get("/api/tracks/random?limit=10").json()}
    p = client.post("/api/playlists", json={"name": "Mine", "trackIds": [ids["Opening"]]}).json()
    recs = lambda pid: [r["title"] for r in client.get(f"/api/playlists/{pid}/recommendations").json()]

    for _ in range(3):
        assert client.post(f"/api/tracks/{ids['Closer']}/skipped").status_code == 200
    assert recs(p["id"])[-1] == "Closer"  # same album, but skipped: last

    client.post(f"/api/playlists/{p['id']}/tracks", json={"trackIds": [ids["Early"]], "suggested": True})
    entry = next(t for t in client.get(f"/api/playlists/{p['id']}").json()["tracks"] if t["title"] == "Early")
    client.delete(f"/api/playlists/{p['id']}/tracks/{entry['entryId']}")
    assert "Early" not in recs(p["id"])  # taken back out: not suggested for this playlist again

    # Taking out a song that wasn't a suggestion says nothing about it.
    client.post(f"/api/playlists/{p['id']}/tracks", json={"trackIds": [ids["Late"]]})
    entry = next(t for t in client.get(f"/api/playlists/{p['id']}").json()["tracks"] if t["title"] == "Late")
    client.delete(f"/api/playlists/{p['id']}/tracks/{entry['entryId']}")
    assert "Late" in recs(p["id"])
