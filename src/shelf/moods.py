"""Mood mixes: Workout, Chill, Party, Feel Good, Melancholy and Heavy.

A song's mood comes from two things, both classic and explainable:

- How it sounds. Its sound fingerprint (sound.py) and energy are ranked against the rest of the
  library (0 = the calmest, darkest, least danceable on the shelf, 1 = the most), so a mood means
  the same whichever engine measured the songs, and fits whatever music someone has. Tempo and
  key (major or minor) come from analysis.py. Both are guesses that are often a little off (a
  tempo read at half or double speed, a key's mode mistaken), so they nudge a song's fit rather
  than decide it alone.
- What it is. Its genres, from its tag and from MusicBrainz's genres for its artist (genres.py),
  each lean towards or away from each mood (GENRES below: metal is Heavy and Workout, never
  Chill). A song whose genres are strongly against a mood is left out of it, however it measured.

Each mix is then made to hang together: the songs that fit a mood best set how it sounds, and
every other song counts more the closer its fingerprint is to theirs. Only the best fitting
songs go on to be picked from, leaning towards the ones this person plays and likes (but never
only those), with a pinch of chance that changes every day, so a mix stays the same all day and
changes the next. No artist or album takes more than two places, and a song is there once
(not its live version as well).
"""

from __future__ import annotations

import json
import random
import re
from typing import Callable, NamedTuple

from .videos import fold

_CENTROID, _FLATNESS, _DANCE = 26, 30, 50  # positions in the sound fingerprint
MIN_MEASURED = 50  # fewer measured songs than this can't say much about moods
MIN_SONGS = 15  # a mood with fewer fitting songs isn't shown
SIZE = 30
CORE = 15  # the best fitting songs, which set how a mood's mix sounds
POOL = 3  # picked from the best SIZE * POOL fits


class Song(NamedTuple):
    energy: float  # 0..1, ranked
    dance: float  # 0..1, ranked
    bright: float  # 0..1, ranked
    noisy: float  # 0..1, ranked (spectral flatness: distortion, cymbals, noise)
    bpm: float | None
    scale: str | None  # "major", "minor" or None
    genres: frozenset = frozenset()  # lowercase, as genres.song_genres gives them


# How each genre leans for each mood: +2 belongs, +1 leans towards, -1 leans away, -2 never.
# A song's genres are matched by the words in them ("melodic death metal" is death and metal),
# and the strongest lean each way counts.
GENRES: dict[str, dict[str, int]] = {
    "workout": {"metal": 2, "metalcore": 2, "hardcore": 2, "punk": 2, "hard rock": 2, "drum and bass": 2, "dubstep": 2,
                "edm": 2, "electronic": 1, "techno": 2, "house": 1, "trance": 2, "hip hop": 1, "rap": 1, "grunge": 1,
                "rock": 1, "industrial": 2, "electro": 1,
                "ambient": -2, "classical": -2, "jazz": -1, "folk": -1, "acoustic": -2, "singer songwriter": -1,
                "ballad": -2, "lo fi": -2, "easy listening": -2, "new age": -2, "blues": -1, "soul": -1, "reggae": -1,
                "country": -1, "chill": -2, "downtempo": -2, "lounge": -2, "doom": -1, "vocal": -1, "standards": -2,
                "soft rock": -1},
    "chill": {"ambient": 2, "lo fi": 2, "chill": 2, "chillout": 2, "downtempo": 2, "trip hop": 2, "acoustic": 2,
              "folk": 1, "jazz": 1, "soul": 1, "singer songwriter": 1, "classical": 1, "bossa nova": 2,
              "easy listening": 2, "lounge": 2, "new age": 2, "dream pop": 1, "soft rock": 1, "reggae": 1, "ballad": 1,
              "standards": 1, "vocal": 1,
              "metal": -2, "metalcore": -2, "hardcore": -2, "punk": -2, "thrash": -2, "grindcore": -2, "hard rock": -2,
              "dubstep": -2, "drum and bass": -2, "industrial": -2, "techno": -1, "rap": -1, "hip hop": -1, "grunge": -2,
              "edm": -1, "rock": -1},
    "party": {"dance": 2, "disco": 2, "funk": 2, "house": 2, "edm": 2, "electronic": 1, "pop": 1, "hip hop": 1,
              "rap": 1, "reggaeton": 2, "latin": 1, "dancehall": 2, "techno": 1, "synthpop": 2, "synth pop": 2,
              "new wave": 1, "r&b": 1, "rnb": 1, "electro": 2, "eurodance": 2, "ska": 1, "pop punk": 1,
              "metal": -2, "thrash": -2, "ambient": -2, "classical": -2, "glam": 1, "folk": -1, "singer songwriter": -1, "doom": -2,
              "post rock": -2, "blues": -1, "acoustic": -1, "ballad": -2, "new age": -2, "jazz": -1, "sludge": -2,
              "black metal": -2, "death metal": -2},
    "feel-good": {"pop": 1, "funk": 2, "disco": 2, "soul": 1, "motown": 2, "reggae": 2, "ska": 2, "pop punk": 2,
                  "surf": 2, "new wave": 1, "synthpop": 1, "synth pop": 1, "britpop": 1, "power pop": 2,
                  "rock and roll": 2, "rock & roll": 2, "rockabilly": 2, "doo wop": 2, "country": 1, "dance": 1,
                  "gospel": 1, "glam": 1, "metal": -1,
                  "doom": -2, "black metal": -2, "death metal": -2, "sludge": -2, "emo": -1, "goth": -2, "gothic": -2,
                  "darkwave": -2, "industrial": -2, "depressive": -2, "post punk": -1, "grunge": -1, "metalcore": -1,
                  "thrash": -1, "slowcore": -2, "shoegaze": -1},
    "melancholy": {"emo": 2, "sad": 2, "slowcore": 2, "shoegaze": 1, "post rock": 1, "singer songwriter": 1,
                   "folk": 1, "blues": 1, "ballad": 2, "goth": 1, "gothic": 1, "darkwave": 2, "dream pop": 1,
                   "acoustic": 1, "classical": 1, "post punk": 1, "grunge": 1, "doom": 1, "trip hop": 1, "indie": 1,
                   "dance": -2, "disco": -2, "funk": -2, "party": -2, "edm": -1, "house": -2, "techno": -1, "ska": -2,
                   "reggaeton": -2, "pop punk": -1, "eurodance": -2, "surf": -2, "rock and roll": -1, "rockabilly": -2,
                   "thrash": -1, "hardcore": -1, "motown": -1},
    "heavy": {"metal": 2, "hardcore": 2, "metalcore": 2, "thrash": 2, "death": 2, "black metal": 2, "doom": 2,
              "sludge": 2, "grindcore": 2, "industrial": 2, "nu metal": 2, "hard rock": 2, "punk": 1, "grunge": 1,
              "post hardcore": 2, "deathcore": 2, "djent": 2, "stoner": 2, "noise": 1,
              "pop": -1, "jazz": -2, "soul": -2, "folk": -2, "ambient": -2, "classical": -2, "reggae": -2,
              "disco": -2, "country": -2, "singer songwriter": -2, "acoustic": -2, "funk": -1, "motown": -2,
              "easy listening": -2, "new age": -2, "bossa nova": -2, "ballad": -2, "r&b": -2, "rnb": -2,
              "lo fi": -2, "chill": -2, "standards": -2, "vocal": -1, "soft rock": -2},
}
# Words that make a genre something else: "pop punk" isn't pop for Heavy's sake.
_COMPOUNDS = ("pop punk", "pop rock", "post punk", "post rock", "post hardcore", "nu metal", "black metal",
              "death metal", "hard rock", "soft rock", "lo fi", "trip hop", "hip hop", "drum and bass",
              "singer songwriter", "easy listening", "new age", "bossa nova", "dream pop", "synth pop", "new wave",
              "rock and roll", "rock & roll", "doo wop", "power pop")


def _words(genre: str, table: dict[str, int]) -> set[str]:
    """The genre words in a genre name that a mood has a say on. A two-word genre the mood knows
    stands for its words ("pop punk" is not "pop" for Heavy); otherwise each word counts
    ("melodic death metal" is death and metal)."""
    g = f" {genre.replace('-', ' ').replace('_', ' ').replace('/', ' ')} ".replace(" trash metal ", " thrash metal ")
    found = {c for c in _COMPOUNDS if f" {c} " in g and c in table}
    for c in found:
        g = g.replace(f" {c} ", " ")
    return found | set(g.split()) | {genre}


def genre_lean(mood: str, genres: frozenset | set) -> int:
    """How a song's genres lean for a mood, -2..2 (0 without genres, or none that say)."""
    table = GENRES[mood]
    leans = [table[w] for g in genres for w in _words(g, table) if w in table]
    if not leans:
        return 0
    return max(0, max(leans)) + min(0, min(leans))


def _between(bpm, lo, hi):
    """Whether the tempo is in range, also read at half or double speed (a common slip)."""
    return bpm is not None and any(lo <= b <= hi for b in (bpm, bpm * 2, bpm / 2))


def _key(s: Song, want: str) -> float:
    return 0.45 if s.scale == want else -0.45 if s.scale else 0.0


def _with_genres(mood: str, fit: Callable[[Song], float | None]) -> Callable[[Song], float | None]:
    """A mood's fit by sound, with its genres leaning it (and ruling it out when they're strongly against)."""
    def both(s: Song) -> float | None:
        lean = genre_lean(mood, s.genres)
        if lean <= -2:
            return None
        f = fit(s)
        return None if f is None else f + 0.35 * lean
    return both


# key, name, description, colour, fit: how well a song fits (higher is better), None if it doesn't.
MOODS: list[tuple[str, str, str, str, Callable[[Song], float | None]]] = [
    ("workout", "Workout", "High-energy songs at a running pace", "#e03131", _with_genres("workout",
     lambda s: s.energy + 0.5 * s.dance + 0.2 * s.noisy if s.energy >= 0.6 and _between(s.bpm, 115, 185) else None)),
    ("chill", "Chill", "Calm, unhurried songs to wind down with", "#1098ad", _with_genres("chill",
     lambda s: (1 - s.energy) + 0.3 * (1 - s.bright) + 0.3 * (1 - s.noisy)
     if s.energy <= 0.4 and s.noisy <= 0.7 and s.bright <= 0.8 and (s.bpm is None or s.bpm <= 125) else None)),
    ("party", "Party", "Danceable songs with a steady beat", "#d6336c", _with_genres("party",
     lambda s: s.dance + 0.5 * s.energy + 0.2 * s.bright
     if s.dance >= 0.55 and s.energy >= 0.4 and _between(s.bpm, 95, 135) else None)),
    ("feel-good", "Feel Good", "Bright, upbeat songs, mostly in major keys", "#f59f00", _with_genres("feel-good",
     lambda s: 0.5 * s.energy + 0.5 * s.bright + 0.3 * s.dance + _key(s, "major")
     if s.energy >= 0.4 and s.bright >= 0.4 and s.noisy <= 0.8 else None)),
    ("melancholy", "Melancholy", "Slower, darker songs, mostly in minor keys", "#5c7cfa", _with_genres("melancholy",
     lambda s: (1 - s.energy) + (1 - s.bright) + _key(s, "minor")
     if s.energy <= 0.5 and s.bright <= 0.6 and s.dance <= 0.8 else None)),
    ("heavy", "Heavy", "The loudest, most intense songs on your shelf", "#495057", _with_genres("heavy",
     lambda s: s.energy + s.noisy if s.energy >= 0.7 and s.noisy >= 0.5 else None)),
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


def features(rows, energy: dict[int, float], genres_of: Callable | None = None) -> dict[int, Song]:
    """Each measured song's mood features, ranked against the rest of the library. Empty when
    too little of the library is measured to say. `genres_of(row)`: the song's genres."""
    measured = [r for r in rows if r["sound"] and r["id"] in energy]
    if len(measured) < MIN_MEASURED:
        return {}
    vecs = {r["id"]: json.loads(r["sound"]) for r in measured}
    dance = _rank({i: v[_DANCE] for i, v in vecs.items()})
    bright = _rank({i: v[_CENTROID] for i, v in vecs.items()})
    noisy = _rank({i: v[_FLATNESS] for i, v in vecs.items()})
    return {r["id"]: Song(energy[r["id"]], dance[r["id"]], bright[r["id"]], noisy[r["id"]],
                          r["bpm"] or None, _scale(r["musical_key"]),
                          frozenset(genres_of(r)) if genres_of else frozenset()) for r in measured}


def _sounds(rows, ids) -> dict:
    """Each song's fingerprint scaled against the library's (every number counts alike)."""
    import numpy as np

    ids = list(ids)
    by = {r["id"]: r for r in rows}
    m = np.array([json.loads(by[i]["sound"]) for i in ids], dtype=float)
    m = (m - m.mean(axis=0)) / (m.std(axis=0) + 1e-9)
    m /= np.linalg.norm(m, axis=1, keepdims=True) + 1e-9
    return dict(zip(ids, m))


def mood_mixes(rows, energy: dict[int, float], score: dict[int, float], seed: str,
               genres_of: Callable | None = None) -> list[dict]:
    """The moods that have enough fitting songs: [{key, name, description, color, ids}]."""
    import numpy as np

    songs = features(rows, energy, genres_of)
    if not songs:
        return []
    measured = [r for r in rows if r["id"] in songs]
    sounds = _sounds(rows, songs)
    top = max(score.values(), default=0) or 1.0

    out = []
    for key, name, description, color, fit in MOODS:
        rng = random.Random(f"{seed}:{key}")
        fits = {r["id"]: f for r in measured if (f := fit(songs[r["id"]])) is not None}
        if len(fits) < MIN_SONGS:
            continue
        # How the best fits sound, and how close every other song is to that.
        core = sorted(fits, key=lambda i: -fits[i])[:CORE]
        centre = np.mean([sounds[i] for i in core], axis=0)
        centre /= np.linalg.norm(centre) + 1e-9
        fitted = {i: f + 0.5 * float(sounds[i] @ centre) for i, f in fits.items()}
        pool = sorted(fitted, key=lambda i: -fitted[i])[:SIZE * POOL]
        # Among the best fits: the closest first, nudged by what this person plays and by the day.
        span = (fitted[pool[0]] - fitted[pool[-1]]) or 1.0
        picked = sorted(pool, key=lambda i: -((fitted[i] - fitted[pool[-1]]) / span + 0.4 * score.get(i, 0) / top
                                              + 0.3 * rng.random()))
        by_id = {r["id"]: r for r in measured}
        ids, per_artist, per_album, songs_in = [], {}, {}, set()
        for i in picked:
            r = by_id[i]
            artist = fold(r["album_artist_name"] or r["artist"] or "")
            same = (artist, fold(re.sub(r"\s*[\(\[].*$", "", r["title"] or "")))  # one version of a song
            if per_artist.get(artist, 0) >= 2 or per_album.get(r["album_id"], 0) >= 2 or same in songs_in:
                continue
            songs_in.add(same)
            per_artist[artist] = per_artist.get(artist, 0) + 1
            per_album[r["album_id"]] = per_album.get(r["album_id"], 0) + 1
            ids.append(i)
            if len(ids) >= SIZE:
                break
        if len(ids) >= MIN_SONGS:
            rng.shuffle(ids)  # the best fits, not in order of fit
            out.append({"key": key, "name": name, "description": description, "color": color, "ids": ids})
    return out
