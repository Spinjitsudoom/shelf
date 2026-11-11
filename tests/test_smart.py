"""Smart playlists: songs picked by rules ("not played in 6 months", "under 100 BPM", "added this
week"), worked out each time, so the playlist keeps itself up to date."""

import pytest
from fastapi.testclient import TestClient

from shelf import smart

DAY = 86400
NOW = 1_700_000_000


def song(i, **kw):
    base = {"id": i, "title": f"Song {i}", "artist": "Band", "album_title": "Album", "album_artist_name": "Band",
            "genre": None, "year": 2000, "bpm": None, "duration": 200.0, "codec": "mp3", "added_at": NOW - 400 * DAY}
    return base | kw


def pick(rows, rules, **facts):
    f = smart.Facts(plays=facts.get("plays", {}), last=facts.get("last", {}), likes=facts.get("likes", set()),
                    moods=facts.get("moods", {}))
    return smart.songs(rows, f, smart.validate(rules), now=NOW, seed="s")


def cond(field, op, value=None):
    return {"field": field, "op": op, "value": value}


def test_not_played_in_six_months():
    rows = [song(1), song(2), song(3)]
    last = {1: NOW - 10 * DAY, 2: NOW - 300 * DAY}  # 3: never played
    ids = pick(rows, {"conditions": [cond("lastPlayed", "notWithin", 180)]}, last=last)
    assert sorted(ids) == [2, 3]
    assert pick(rows, {"conditions": [cond("lastPlayed", "never")]}, last=last) == [3]


def test_tempo_and_favourites_together():
    rows = [song(1, bpm=90), song(2, bpm=128), song(3, bpm=None), song(4, bpm=80)]
    rules = {"match": "all", "conditions": [cond("bpm", "atMost", 100), cond("favourite", "is", True)]}
    assert pick(rows, rules, likes={1, 2, 3}) == [1]  # a song not measured yet has no tempo to match


def test_added_this_week_and_any_of():
    rows = [song(1, added_at=NOW - 2 * DAY), song(2), song(3, genre="Heavy Metal; Thrash Metal")]
    assert pick(rows, {"conditions": [cond("added", "within", 7)]}) == [1]
    rules = {"match": "any", "conditions": [cond("added", "within", 7), cond("genre", "contains", "metal")]}
    assert sorted(pick(rows, rules)) == [1, 3]
    assert sorted(pick(rows, {"conditions": [cond("genre", "isNot", "thrash metal")]})) == [1, 2]


def test_text_numbers_and_flags():
    rows = [song(1, artist="Mötley Crüe", year=1987, duration=320, codec="flac"), song(2, year=1999), song(3, year=2010)]
    assert pick(rows, {"conditions": [cond("artist", "is", "motley crue")]}) == [1]  # accents and case don't matter
    assert sorted(pick(rows, {"conditions": [cond("year", "between", [1985, 2000])]})) == [1, 2]
    assert pick(rows, {"conditions": [cond("duration", "atLeast", 5)]}) == [1]  # minutes
    assert pick(rows, {"conditions": [cond("lossless", "is", True)]}) == [1]
    assert sorted(pick(rows, {"conditions": [cond("plays", "is", 0)]}, plays={1: 3})) == [2, 3]
    assert pick(rows, {"conditions": [cond("mood", "is", "chill")]}, moods={2: {"chill"}}) == [2]


def test_sorting_and_limits():
    rows = [song(i) for i in range(1, 6)]
    plays = {1: 1, 2: 9, 3: 5}
    rules = {"conditions": [cond("plays", "atLeast", 1)], "sort": "mostPlayed", "limit": 2}
    assert pick(rows, rules, plays=plays) == [2, 3]
    everything = {"conditions": [], "sort": "random", "limit": 3}
    assert pick(rows, everything) == pick(rows, everything)  # the same all day, not on every look
    assert len(pick(rows, everything)) == 3


def test_rules_are_checked():
    for bad in ({"conditions": [cond("rating", "is", 5)]}, {"conditions": [cond("bpm", "atMost", "fast")]},
                {"conditions": [cond("genre", "between", "x")]}, {"conditions": [cond("year", "between", [2000])]},
                {"conditions": [cond("mood", "is", "angry")]}, {"conditions": [], "limit": 0},
                {"conditions": [cond("genre", "contains", "")]}, {"match": "some", "conditions": []}):
        with pytest.raises(ValueError):
            smart.validate(bad)


def test_described_in_words():
    rules = smart.validate({"conditions": [cond("lastPlayed", "notWithin", 180), cond("bpm", "atMost", 100)]})
    assert smart.describe(rules) == "Songs not played in 6 months and at most 100 BPM"
    rules = smart.validate({"match": "any", "conditions": [cond("added", "within", 7), cond("favourite", "is", True)],
                            "sort": "mostPlayed", "limit": 50})
    assert smart.describe(rules) == "Songs added in the last week or in your Favourites. Up to 50, most played first"
    assert smart.describe(smart.validate({"conditions": []})) == "All your songs"


# ---------- in the app ----------

def login(c, username="admin", password="hunter2"):
    assert c.post("/api/login", json={"username": username, "password": password}).status_code == 200


def test_a_smart_playlist_fills_itself(client):
    login(client)
    rules = {"conditions": [{"field": "album", "op": "is", "value": "First"}], "sort": "title"}
    made = client.post("/api/playlists", json={"name": "Just First", "rules": rules}).json()
    assert made["smart"] and made["trackCount"] == 2 and made["rulesText"] == "Songs from the album “First”. Title order"
    pid = made["id"]
    got = client.get(f"/api/playlists/{pid}").json()
    assert [t["title"] for t in got["tracks"]] == ["Closer", "Opening"] and got["smart"]["sort"] == "title"

    # Played songs drop out of a "never played" playlist straight away.
    client.patch(f"/api/playlists/{pid}", json={"rules": {"conditions": [{"field": "plays", "op": "is", "value": 0}]}})
    first = got["tracks"][0]["id"]
    client.post(f"/api/tracks/{first}/played")
    after = client.get(f"/api/playlists/{pid}").json()
    assert first not in [t["id"] for t in after["tracks"]] and after["trackCount"] == 3

    # Songs can't be added or taken out by hand: the rules decide.
    r = client.post(f"/api/playlists/{pid}/tracks", json={"trackIds": [first]})
    assert r.status_code == 400 and "rules" in r.json()["detail"]
    assert client.patch(f"/api/playlists/{pid}", json={"rules": {"conditions": [{"field": "rating", "op": "is", "value": 5}]}}).status_code == 400
    assert client.get(f"/api/playlists/{pid}/recommendations").json() == []

    preview = client.post("/api/smart/preview", json={"rules": {"conditions": [{"field": "lossless", "op": "is", "value": True}]}}).json()
    assert preview["count"] == 2 and preview["text"] == "Songs in lossless quality"
    assert client.post("/api/smart/preview", json={"rules": {"match": "most"}}).status_code == 400

    # Ordinary playlists stay ordinary.
    plain = client.post("/api/playlists", json={"name": "Plain"}).json()
    assert plain["smart"] is None


def test_smart_playlists_in_subsonic_apps(client):
    login(client)
    pid = client.post("/api/playlists", json={"name": "Flac", "rules": {"conditions": [{"field": "lossless", "op": "is", "value": True}]}}).json()["id"]
    pw = client.post("/api/me/subsonic").json()["password"]
    c = TestClient(client.app)
    r = c.get("/rest/getPlaylist", params={"u": "admin", "p": pw, "f": "json", "id": pid}).json()["subsonic-response"]
    assert sorted(e["title"] for e in r["playlist"]["entry"]) == ["Early", "Late"] and r["playlist"]["songCount"] == 2
