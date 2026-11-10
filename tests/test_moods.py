"""Mood mixes (Workout, Chill...) from how songs sound, ranked against the rest of the library."""

import json
import random

from shelf import moods

N = 60  # fingerprint numbers (only a few positions matter here)


def song(i, *, energy, dance=0.5, bright=0.5, bpm=120, key="A minor", artist=None):
    vec = [0.0] * 52
    vec[moods._DANCE] = dance
    vec[moods._CENTROID] = bright * 4000
    vec[moods._FLATNESS] = 0.1
    return {"id": i, "artist": artist or f"Artist {i % 20}", "album_artist_name": None, "album_id": i % 25,
            "bpm": bpm, "musical_key": key, "sound": json.dumps(vec), "_energy": energy}


def library(n=200, seed=1):
    rng = random.Random(seed)
    rows = [song(i, energy=rng.random(), dance=rng.random(), bright=rng.random(),
                 bpm=rng.choice([70, 85, 100, 118, 128, 140, 160]), key=rng.choice(["A minor", "C major", "E minor", "G major"]))
            for i in range(n)]
    return rows, {r["id"]: r["_energy"] for r in rows}


def by_id(rows):
    return {r["id"]: r for r in rows}


def test_workout_is_energetic_and_at_a_running_pace():
    rows, energy = library()
    mixes = {m["key"]: m for m in moods.mood_mixes(rows, energy, {}, "day-1")}
    picked = [by_id(rows)[i] for i in mixes["workout"]["ids"]]
    assert len(picked) >= 15
    assert all(r["_energy"] >= 0.6 for r in picked)
    assert all(115 <= r["bpm"] <= 175 for r in picked)


def test_chill_is_calm_and_melancholy_is_minor():
    rows, energy = library()
    mixes = {m["key"]: m for m in moods.mood_mixes(rows, energy, {}, "day-1")}
    assert all(by_id(rows)[i]["_energy"] <= 0.4 for i in mixes["chill"]["ids"])
    sad = [by_id(rows)[i] for i in mixes["melancholy"]["ids"]]
    assert sad and all(r["musical_key"].endswith("minor") for r in sad)
    happy = [by_id(rows)[i] for i in mixes["feel-good"]["ids"]]
    assert happy and all(r["musical_key"].endswith("major") for r in happy)


def test_no_artist_takes_over():
    rows, energy = library()
    for r in rows[:100]:
        r["artist"] = "Metallica"  # half the library by one band
    for m in moods.mood_mixes(rows, energy, {}, "day-1"):
        artists = [by_id(rows)[i]["artist"] for i in m["ids"]]
        assert artists.count("Metallica") <= 2, (m["key"], artists)


def test_leans_towards_what_you_play_and_changes_daily():
    rows, energy = library()
    fav = [r["id"] for r in rows if r["_energy"] >= 0.7 and 115 <= r["bpm"] <= 175][:3]
    score = {i: 1.0 for i in fav}
    workout = next(m for m in moods.mood_mixes(rows, energy, score, "day-1") if m["key"] == "workout")
    assert set(fav) <= set(workout["ids"])
    other_day = next(m for m in moods.mood_mixes(rows, energy, score, "day-2") if m["key"] == "workout")
    assert workout["ids"] != other_day["ids"]
    again = next(m for m in moods.mood_mixes(rows, energy, score, "day-1") if m["key"] == "workout")
    assert workout["ids"] == again["ids"]  # the same all day


def test_unmeasured_library_gets_no_moods():
    rows, energy = library(n=30)
    assert moods.mood_mixes(rows, energy, {}, "day-1") == []  # too few measured songs to say
    rows, _ = library()
    assert moods.mood_mixes(rows, {}, {}, "day-1") == []  # nothing measured yet


def test_moods_are_in_made_for_you(client, monkeypatch):
    assert client.post("/api/login", json={"password": "hunter2"}).status_code == 200
    ids = [t["id"] for t in client.get("/api/tracks/random?limit=4").json()]
    seen = {}

    def fake(rows, energy, score, seed):
        seen["seed"] = seed
        return [{"key": "workout", "name": "Workout", "description": "High-energy songs at a running pace",
                 "color": "#e03131", "ids": ids}]

    monkeypatch.setattr(moods, "mood_mixes", fake)
    listed = {m["key"]: m for m in client.get("/api/mixes").json()}
    assert listed["workout"]["name"] == "Workout" and listed["workout"]["trackCount"] == 4
    assert sorted(t["id"] for t in client.get("/api/mixes/workout").json()["tracks"]) == sorted(ids)
    assert seen["seed"]  # a seed for the day
