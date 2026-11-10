"""Mood mixes: Workout, Chill, Party, Feel Good, Melancholy and Heavy, from how songs sound.

Each song's sound fingerprint (sound.py) and energy are ranked against the rest of the library
(0 = the calmest, darkest, least danceable on the shelf, 1 = the most), so a mood means the same
whichever engine measured the songs, and fits whatever music someone has: Heavy on a jazz shelf
is its most intense jazz. Tempo and key (major or minor) come from analysis.py.

Each mood picks the songs that fit it best, leaning towards the ones this person plays and likes
(but never only those), with a pinch of chance that changes every day, so a mix stays the same
all day and changes the next. No artist or album takes more than two places.
"""

from __future__ import annotations

import json
import random
from typing import Callable, NamedTuple

from .videos import fold

_CENTROID, _FLATNESS, _DANCE = 26, 30, 50  # positions in the sound fingerprint
MIN_MEASURED = 50  # fewer measured songs than this can't say much about moods
MIN_SONGS = 15  # a mood with fewer fitting songs isn't shown
SIZE = 30


class Song(NamedTuple):
    energy: float  # 0..1, ranked
    dance: float  # 0..1, ranked
    bright: float  # 0..1, ranked
    noisy: float  # 0..1, ranked (spectral flatness: distortion, cymbals, noise)
    bpm: float | None
    scale: str | None  # "major", "minor" or None


def _between(bpm, lo, hi):
    return bpm is not None and lo <= bpm <= hi


# key, name, description, colour, fit: how well a song fits (higher is better), None if it doesn't.
MOODS: list[tuple[str, str, str, str, Callable[[Song], float | None]]] = [
    ("workout", "Workout", "High-energy songs at a running pace", "#e03131",
     lambda s: s.energy + 0.5 * s.dance if s.energy >= 0.65 and _between(s.bpm, 115, 190) else None),
    ("chill", "Chill", "Calm, unhurried songs to wind down with", "#1098ad",
     lambda s: (1 - s.energy) + 0.3 * (1 - s.bright) if s.energy <= 0.35 and (s.bpm is None or s.bpm <= 115) else None),
    ("party", "Party", "Danceable songs with a steady beat", "#d6336c",
     lambda s: s.dance + 0.5 * s.energy if s.dance >= 0.6 and s.energy >= 0.45 and _between(s.bpm, 95, 135) else None),
    ("feel-good", "Feel Good", "Bright, upbeat songs in major keys", "#f59f00",
     lambda s: 0.5 * s.energy + 0.5 * s.bright + 0.3 * s.dance if s.scale == "major" and s.energy >= 0.4 and s.bright >= 0.4 else None),
    ("melancholy", "Melancholy", "Slower, darker songs in minor keys", "#5c7cfa",
     lambda s: (1 - s.energy) + (1 - s.bright) if s.scale == "minor" and s.energy <= 0.45 and s.bright <= 0.6 else None),
    ("heavy", "Heavy", "The loudest, most intense songs on your shelf", "#495057",
     lambda s: s.energy + s.noisy if s.energy >= 0.8 and s.noisy >= 0.5 else None),
]


def _rank(values: dict[int, float]) -> dict[int, float]:
    """Each value's place among all of them, 0..1 (ties share the middle of their places)."""
    import bisect

    ordered = sorted(values.values())
    n = len(ordered)
    out = {}
    for k, v in values.items():
        lo, hi = bisect.bisect_left(ordered, v), bisect.bisect_right(ordered, v)
        out[k] = ((lo + hi - 1) / 2) / max(1, n - 1)
    return out


def _scale(key: str | None) -> str | None:
    if not key:
        return None
    return "minor" if key.endswith("minor") else "major" if key.endswith("major") else None


def features(rows, energy: dict[int, float]) -> dict[int, Song]:
    """Each measured song's mood features, ranked against the rest of the library. Empty when
    too little of the library is measured to say."""
    measured = [r for r in rows if r["sound"] and r["id"] in energy]
    if len(measured) < MIN_MEASURED:
        return {}
    vecs = {r["id"]: json.loads(r["sound"]) for r in measured}
    dance = _rank({i: v[_DANCE] for i, v in vecs.items()})
    bright = _rank({i: v[_CENTROID] for i, v in vecs.items()})
    noisy = _rank({i: v[_FLATNESS] for i, v in vecs.items()})
    return {r["id"]: Song(energy[r["id"]], dance[r["id"]], bright[r["id"]], noisy[r["id"]],
                          r["bpm"] or None, _scale(r["musical_key"])) for r in measured}


def mood_mixes(rows, energy: dict[int, float], score: dict[int, float], seed: str) -> list[dict]:
    """The moods that have enough fitting songs: [{key, name, description, color, ids}]."""
    songs = features(rows, energy)
    if not songs:
        return []
    measured = [r for r in rows if r["id"] in songs]
    top = max(score.values(), default=0) or 1.0

    out = []
    for key, name, description, color, fit in MOODS:
        rng = random.Random(f"{seed}:{key}")
        scored = []
        for r in measured:
            f = fit(songs[r["id"]])
            if f is not None:
                scored.append((f + 0.6 * score.get(r["id"], 0) / top + 0.35 * rng.random(), r))
        scored.sort(key=lambda x: -x[0])
        ids, per_artist, per_album = [], {}, {}
        for _s, r in scored:
            artist = fold(r["album_artist_name"] or r["artist"] or "")
            if per_artist.get(artist, 0) >= 2 or per_album.get(r["album_id"], 0) >= 2:
                continue
            per_artist[artist] = per_artist.get(artist, 0) + 1
            per_album[r["album_id"]] = per_album.get(r["album_id"], 0) + 1
            ids.append(r["id"])
            if len(ids) >= SIZE:
                break
        if len(ids) >= MIN_SONGS:
            rng.shuffle(ids)  # the best fits, not in order of fit
            out.append({"key": key, "name": name, "description": description, "color": color, "ids": ids})
    return out
