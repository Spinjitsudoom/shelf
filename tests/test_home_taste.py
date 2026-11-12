"""Home shaped by taste: favourite artists, "More like …" rows, the artists you follow, and
rows that move up when they're used."""

import time

from shelf import home
from shelf.db import session

DAY = 86400
NOW = 1_800_000_000.0


def track(i, artist, album_id=1, album_artist=None):
    return {"id": i, "artist": artist, "album_artist_name": album_artist, "album_id": album_id}


def test_taste_adds_up_plays_and_follows():
    tracks = [track(1, "Band"), track(2, "Band"), track(3, "Other"), track(4, "Quiet One")]
    score = {1: 1.0, 2: 0.5, 3: 0.25}
    taste = home.artist_taste(tracks, score, follows={"quiet one", "other"})
    assert taste["band"] == ("Band", 1.5)
    assert taste["other"] == ("Other", 0.25 + home.FOLLOW_BONUS)
    assert taste["quiet one"] == ("Quiet One", home.FOLLOW_BONUS)  # followed, never played


def test_seed_artists_are_two_of_the_top_four_and_change_by_day():
    taste = {k: (k.title(), s) for k, s in [("a", 9), ("b", 7), ("c", 5), ("d", 3), ("e", 1)]}
    picks = {tuple(home.seed_artists(taste, f"day-{i}")) for i in range(40)}
    assert all(len(p) == 2 and "E" not in p for p in picks)
    assert all(taste[p[0].lower()][1] > taste[p[1].lower()][1] for p in picks)  # best liked first
    assert len(picks) > 1  # not the same pair every day
    assert home.seed_artists(taste, "x") == home.seed_artists(taste, "x")  # same all day
    assert home.seed_artists({"a": ("A", 1)}, "x") == ["A"]


def test_more_like_leaves_out_the_artists_own_albums():
    picks = [{"albumId": 1, "artist": "Band"}, {"albumId": 2, "artist": "Other"},
             {"albumId": 2, "artist": "Other"}, {"albumId": 3, "artist": "Guest", "albumArtist": "Band"},
             {"albumId": 4, "artist": "Third"}]
    assert home.like_albums(picks, "Band") == [2, 4]
    assert home.like_albums(picks, "Band", limit=1) == [2]


def test_from_artists_you_follow_newest_then_least_played():
    def album(key, artist, added):
        return {"key": key, "artist": artist, "added_at": added}
    albums = [album("old-much", "Band", NOW - 90 * DAY), album("old-little", "Band", NOW - 80 * DAY),
              album("new", "Band", NOW - 2 * DAY), album("newer", "Band", NOW - DAY),
              album("theirs", "Other", NOW)]
    got = home.following_albums(albums, {"band"}, {"old-much": 9, "old-little": 1}, NOW)
    assert [a["key"] for a in got] == ["newer", "new", "old-little", "old-much"]


def test_rows_people_use_move_up():
    keys = ["mixes", "releases", "following", "recent", "added", "top", "rediscover", "like:A", "like:B"]
    plain = home.order(keys, {}, new_listener=False)
    assert plain == ["mixes", "following", "like:A", "recent", "like:B", "added", "top", "releases", "rediscover"]
    # Someone new to Shelf: what's on the shelf comes before rows built on listening.
    assert home.order(keys, {}, new_listener=True).index("added") < plain.index("added")

    taps = [("rediscover", NOW - i * 3600) for i in range(8)]
    used = home.tap_scores(taps, NOW)
    assert home.order(keys, used, False)[:2] == ["rediscover", "mixes"]
    # Taps fade: two weeks on they count half, two months on hardly at all.
    assert home.tap_scores([("x", NOW - 14 * DAY)], NOW)["x"] == 0.5
    assert home.order(keys, home.tap_scores([(r, at - 60 * DAY) for r, at in taps], NOW), False) == plain
    assert home.tap_scores([("like:Band", NOW)], NOW) == {"like": 1.0}


def login(c):
    assert c.post("/api/login", json={"username": "admin", "password": "hunter2"}).status_code == 200


def test_home_lists_its_rows_in_order(client):
    login(client)
    rows = client.get("/api/home").json()["rows"]
    keys = [r["key"] for r in rows]
    assert keys[0] == "mixes" and "added" in keys and "following" not in keys
    added = next(r for r in rows if r["key"] == "added")
    assert added["title"] == "Recently added" and {a["title"] for a in added["albums"]} == {"First", "Second"}

    client.put("/api/artist/follow", params={"name": "Band"})
    rows = client.get("/api/home").json()["rows"]
    following = next(r for r in rows if r["key"] == "following")
    assert following["title"] == "From artists you follow" and len(following["albums"]) == 2
    assert [r["key"] for r in rows].index("following") == 1

    # Browsing a row for a while counts once...
    for _ in range(5):
        assert client.post("/api/home/used", json={"row": "added"}).status_code == 200
    with session(client.app.state.cfg.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM home_taps").fetchone()[0] == 1
        # ...coming back to it on other days moves it up.
        for day in range(1, 6):
            conn.execute("INSERT INTO home_taps(user_id, row, at) VALUES(1, 'added', ?)", (time.time() - day * DAY,))
    assert [r["key"] for r in client.get("/api/home").json()["rows"]][0] == "added"
    assert client.post("/api/home/used", json={"row": ""}).status_code == 422
