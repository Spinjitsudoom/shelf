"""Making a playlist from a few words: "metal, high energy", "chill 90s", "like Metallica"."""

import json
import random

from shelf import playlist_maker as pm

GENRES = ["Heavy Metal", "Thrash Metal", "Jazz", "Pop Rock", "Hip-Hop"]
ARTISTS = ["Metallica", "Slayer", "Megadeth", "Miles Davis", "Coldplay", "Nas"]


def test_understands_genres_moods_energy_decades_and_artists():
    w = pm.understand("metal, high energy", GENRES, ARTISTS)
    assert w.genres == {"Heavy Metal", "Thrash Metal"} and w.energy == "high" and not w.artists
    w = pm.understand("Chill 90s like Miles Davis", GENRES, ARTISTS)
    assert w.moods == {"chill"} and w.years == (1990, 1999) and w.artists == {"Miles Davis"}
    w = pm.understand("gym", GENRES, ARTISTS)
    assert w.moods == {"workout"}
    w = pm.understand("hip hop from the 2000s", GENRES, ARTISTS)
    assert w.genres == {"Hip-Hop"} and w.years == (2000, 2009)
    assert pm.understand("asdf qwerty", GENRES, ARTISTS).empty
    assert pm.describe(pm.understand("metal, high energy", GENRES, ARTISTS)) == ["Heavy Metal and Thrash Metal", "high energy"]


def library(seed=4):
    rng = random.Random(seed)
    rows, energy = [], {}
    bands = {"Metallica": ("Heavy Metal", 30), "Slayer": ("Thrash Metal", 6), "Megadeth": ("Thrash Metal", 6),
             "Iron Maiden": ("Heavy Metal", 6), "Gojira": ("Heavy Metal", 6), "Miles Davis": ("Jazz", 20),
             "Coldplay": ("Pop Rock", 20)}
    i = 0
    for band, (genre, n) in bands.items():
        for k in range(n):
            vec = [0.0] * 52
            vec[26], vec[30], vec[50] = rng.random() * 4000, rng.random(), rng.random()
            rows.append({"id": i, "artist": band, "album_artist_name": band, "album_id": i // 5, "genre": genre,
                         "year": 1985 + (i % 30), "bpm": rng.choice([90, 120, 140, 160]),
                         "musical_key": rng.choice(["A minor", "C major"]), "sound": json.dumps(vec)})
            energy[i] = rng.random() if genre != "Jazz" else rng.random() * 0.4
            i += 1
    return rows, energy


def recommend(mine, pool, seed, limit):
    """Stand-in for the app's suggestions: same genre first."""
    genres = {t["genre"] for t in mine}
    return sorted(pool, key=lambda t: (t["genre"] not in genres, t["id"]))[:limit]


def test_metal_high_energy_is_metal_with_variety():
    rows, energy = library()
    want = pm.understand("metal, high energy", ["Heavy Metal", "Thrash Metal", "Jazz", "Pop Rock"], [r["artist"] for r in rows])
    ids = pm.make(rows, energy, {}, want, recommend, size=12, seed="s")
    picked = [rows[i] for i in ids]
    assert len(picked) == 12
    assert all("Metal" in r["genre"] for r in picked)
    assert all(energy[r["id"]] >= 0.55 for r in picked)
    assert sum(r["artist"] == "Metallica" for r in picked) <= 4  # five bands share it, not one


def test_like_an_artist_brings_similar_ones():
    rows, energy = library()
    want = pm.understand("like Metallica", [], sorted({r["artist"] for r in rows}))
    picked = [rows[i] for i in pm.make(rows, energy, {}, want, recommend, size=20, seed="s")]
    artists = [r["artist"] for r in picked]
    assert 1 <= artists.count("Metallica") <= 4
    assert len(set(artists) - {"Metallica"}) >= 3
    assert not {"Miles Davis", "Coldplay"} & set(artists)  # similar, not anything


def test_decade_and_mood_without_measurements():
    rows, energy = library()
    want = pm.understand("90s", [], [])
    picked = [rows[i] for i in pm.make(rows, {}, {}, want, recommend, size=10, seed="s")]
    assert picked and all(1990 <= r["year"] <= 1999 for r in picked)
    # A mood with nothing measured still gives songs, from the genres and decades asked for.
    want = pm.understand("chill jazz", ["Jazz"], [])
    picked = [rows[i] for i in pm.make(rows, {}, {}, want, recommend, size=10, seed="s")]
    assert picked and all(r["genre"] == "Jazz" for r in picked)


def test_make_endpoint(client):
    assert client.post("/api/login", json={"password": "hunter2"}).status_code == 200
    r = client.post("/api/playlists/make", json={"prompt": "like Band", "size": 3})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Like Band" and len(body["trackIds"]) >= 1 and body["understood"] == ["like Band"]
    bad = client.post("/api/playlists/make", json={"prompt": "zzzz"})
    assert bad.status_code == 400 and "genre" in bad.json()["detail"]
