import time

from shelf import mixes


def lib():
    rows = []
    n = 0
    for artist, genre, count in [("Sabbath", "Metal", 12), ("Slipknot", "Metal", 10), ("Maneskin", "Rock", 14), ("Ranieri", "Pop", 9)]:
        for i in range(count):
            n += 1
            rows.append({"id": n, "title": f"{artist} {i}", "artist": artist, "album_artist_name": artist,
                         "genre": genre, "album_id": hash(artist) % 1000, "cover_src": None})
    return rows


def fake_recommend(mine, pool, seed, limit):
    return [{"id": t["id"], "artist": t["artist"], "albumArtist": t["album_artist_name"]} for t in pool[:limit]]


def as_json(t):
    return {"id": t["id"], "artist": t["artist"], "albumArtist": t["album_artist_name"]}


def test_daily_mixes_group_artists_by_genre_and_keep_for_the_day():
    rows = lib()
    now = time.time()
    plays = [(1, now - 3600)] * 20 + [(30, now - 7200)] * 10 + [(15, now - 7200)] * 5  # Sabbath, Maneskin, Slipknot
    score = mixes.affinity(plays, {2}, now)
    m = mixes.daily_mixes(rows, score, fake_recommend, "1:2026-300")
    # Ranieri was never played, so there is no Ranieri mix.
    assert [x["artists"] for x in m] == [["Sabbath", "Slipknot"], ["Maneskin"]]
    assert m[0]["description"] == "Sabbath, Slipknot and more"
    first = mixes.finish_daily(m[0], as_json)
    assert len(first) == mixes.MIX_SIZE
    assert all(a["artist"] != b["artist"] or a["artist"] in ("Sabbath", "Slipknot") for a, b in zip(first, first[1:]))
    again = mixes.finish_daily(mixes.daily_mixes(rows, score, fake_recommend, "1:2026-300")[0], as_json)
    assert [t["id"] for t in again] == [t["id"] for t in first]  # same all day
    other_day = mixes.finish_daily(mixes.daily_mixes(rows, score, fake_recommend, "1:2026-301")[0], as_json)
    assert [t["id"] for t in other_day] != [t["id"] for t in first]


def test_new_listener_gets_mixes_from_the_library():
    m = mixes.daily_mixes(lib(), {}, fake_recommend, "9:2026-1")
    assert m and m[0]["artists"][0] == "Maneskin"  # the biggest artist on the shelf


def test_on_repeat_and_rediscover():
    rows = {t["id"]: t for t in lib()}
    now = time.time()
    plays = [(1, now - 86400)] * 3 + [(2, now - 86400)] + [(5, now - 90 * 86400)] * 4 + [(6, now - 90 * 86400)] * 3 + [(6, now - 86400)]
    assert [t["id"] for t in mixes.on_repeat(rows, plays, now)] == [1]
    assert [t["id"] for t in mixes.rediscover(rows, plays, now)] == [5]


def login(client):
    assert client.post("/api/login", json={"password": "hunter2"}).status_code == 200


def test_mix_and_radio_api(client):
    login(client)
    assert client.get("/api/mixes").status_code == 200
    assert client.get("/api/mixes/daily-9").status_code == 404
    tid = client.get("/api/tracks/random?limit=1").json()[0]["id"]
    r = client.get(f"/api/radio?track={tid}").json()
    assert r["tracks"][0]["id"] == tid and r["name"].endswith("Radio")
    a = client.get("/api/radio?artist=band").json()
    assert a["tracks"] and a["name"] == "Band Radio"
    assert client.get("/api/radio").status_code == 400


def test_sounds_like():
    import json
    import numpy as np
    from shelf import sound
    rng = np.random.default_rng(1)
    loud, soft = rng.normal(5, 1, 52), rng.normal(-5, 1, 52)
    rows = [{"id": i, "sound": json.dumps(list((loud if i < 10 else soft) + rng.normal(0, .3, 52)))} for i in range(20)]
    vecs = sound.vectors(rows)
    c = sound.centre(vecs, [0, 1, 2])
    assert sound.similarity(vecs, c, 5) > 0.5 > sound.similarity(vecs, c, 15)
    assert sound.similarity(vecs, c, 99) == 0.0  # not measured


def test_release_matching():
    from shelf.releases import base_title, owns
    shelf = [("aerosmith & yungblud", "one more time"), ("black sabbath", "paranoid")]
    assert owns(shelf, "YUNGBLUD", "One More Time")
    assert owns(shelf, "Black Sabbath", "Paranoid (2009 Remaster)")
    assert not owns(shelf, "Black Sabbath", "Master of Reality")
    assert not owns(shelf, "Yung", "One More Time")  # a whole name, not part of one
    assert base_title("Vol. 4 [Deluxe Edition]") == base_title("Vol 4")
