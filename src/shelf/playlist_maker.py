"""Making a playlist from a few words: "metal, high energy", "chill 90s", "like Metallica".

The words are matched against what Shelf knows, not guessed at by a language model:

- genres in this library ("metal" finds Heavy Metal, Thrash Metal...; "hip hop" finds Hip-Hop);
- artists in this library, anywhere in the words ("like Metallica", "slayer and megadeth");
- the moods of the mood mixes, by their everyday words (gym, relax, sad, dance...);
- energy ("high energy", "slow") and decades ("90s", "the 2000s").

Then songs are picked that fit all of it, with variety: named artists get a few songs each and
the rest are artists that sound like them; any other artist two songs, more only when the
library has too few to fill the playlist. Moods and energy need songs to be measured (sound.py);
until they are, genres, artists and decades still work.
"""

from __future__ import annotations

import random
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Callable

from . import moods

MOOD_WORDS = {
    "workout": ["workout", "work out", "gym", "running", "run", "training", "exercise", "cardio", "lifting"],
    "chill": ["chill", "chilled", "relax", "relaxing", "calm", "mellow", "sleep", "study", "focus", "wind down", "lazy"],
    "party": ["party", "dance", "dancing", "club", "groove", "groovy"],
    "feel-good": ["feel good", "feelgood", "happy", "upbeat", "cheerful", "sunny", "summer", "good vibes"],
    "melancholy": ["sad", "melancholy", "melancholic", "moody", "rainy", "heartbreak", "blue", "gloomy"],
    "heavy": ["heavy", "intense", "aggressive", "hard", "angry", "loud", "brutal"],
}
ENERGY_WORDS = {
    "high": ["high energy", "energetic", "energy", "fast", "hype", "pumped", "pump up", "loud and fast"],
    "low": ["low energy", "slow", "quiet", "soft", "gentle", "slow paced"],
}
FILLER = {"a", "an", "the", "and", "or", "of", "for", "from", "with", "some", "songs", "song", "music", "like",
          "playlist", "mix", "to", "in", "on", "my", "me", "that", "sounds", "sound", "stuff", "vibes", "vibe", "era"}
MOOD_NAMES = {key: name for key, name, *_ in moods.MOODS}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _has(text: str, phrase: str) -> bool:
    return bool(phrase) and f" {phrase} " in f" {text} "


def _drop(text: str, phrase: str) -> str:
    return re.sub(r"\s+", " ", f" {text} ".replace(f" {phrase} ", " ")).strip()


@dataclass
class Want:
    genres: set[str] = field(default_factory=set)
    artists: set[str] = field(default_factory=set)
    moods: set[str] = field(default_factory=set)
    energy: str | None = None  # "high" or "low"
    years: tuple[int, int] | None = None

    @property
    def empty(self) -> bool:
        return not (self.genres or self.artists or self.moods or self.energy or self.years)


def understand(text: str, genres: list[str], artists: list[str]) -> Want:
    """What a description asks for, in terms of this library."""
    want = Want()
    t = norm(text)
    # Longest names first, so "Iron Maiden" wins over "Iron".
    seen = set()
    for a in sorted(artists, key=lambda a: -len(norm(a))):
        n = norm(a)
        if len(n) >= 3 and n not in seen and _has(t, n):
            want.artists.add(a)
            seen.add(n)
            t = _drop(t, n)
    for g in sorted(genres, key=lambda g: -len(norm(g))):
        n = norm(g)
        if len(n) >= 3 and _has(t, n):
            want.genres.add(g)
    for g in want.genres:
        t = _drop(t, norm(g))
    m = re.search(r"\b(?:19)?([5-9]0)s\b", t) or re.search(r"\b(20[0-2]0)s\b", t)
    if m:
        start = int(m.group(1)) + (1900 if len(m.group(1)) == 2 else 0)
        want.years = (start, start + 9)
        t = _drop(t, m.group(0))
    for level, words in ENERGY_WORDS.items():
        for w in sorted(words, key=len, reverse=True):
            if _has(t, w):
                want.energy = want.energy or level
                t = _drop(t, w)
    for mood, words in MOOD_WORDS.items():
        for w in sorted(words, key=len, reverse=True):
            if _has(t, w):
                want.moods.add(mood)
                t = _drop(t, w)
    # What's left: single words that name part of a genre ("metal" for Heavy Metal).
    left = {w for w in t.split() if len(w) >= 3 and w not in FILLER}
    for g in genres:
        if left & set(norm(g).split()):
            want.genres.add(g)
    return want


def _and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def describe(want: Want) -> list[str]:
    """What was understood, in words, for the person to check."""
    out = []
    if want.genres:
        out.append(_and(sorted(want.genres)))
    if want.artists:
        out.append("like " + _and(sorted(want.artists)))
    out += [MOOD_NAMES[m] for m in sorted(want.moods)]
    if want.energy:
        out.append(f"{want.energy} energy")
    if want.years:
        out.append(f"the {want.years[0]}s")
    return out


Recommend = Callable[[list, list, int, int], list]


def make(rows, energy: dict[int, float], score: dict[int, float], want: Want, recommend: Recommend,
         size: int = 30, seed: str = "") -> list[int]:
    """Song ids for the playlist, in a playing order where an artist doesn't repeat back to back."""
    rng = random.Random(f"{seed}:{norm(' '.join(describe(want)))}")
    named = {norm(a) for a in want.artists}
    artist_of = lambda r: norm(r["album_artist_name"] or r["artist"] or "")
    by_named = lambda r: norm(r["artist"]) in named or artist_of(r) in named

    def allowed(r) -> bool:
        if want.genres and r["genre"] not in want.genres:
            return False
        if want.years and not (r["year"] and want.years[0] <= r["year"] <= want.years[1]):
            return False
        return True

    # Candidates and a head start for each: songs by named artists, then the ones that sound like them.
    bonus: dict[int, float] = {}
    if named:
        seeds = [r for r in rows if by_named(r)]
        for r in seeds:
            bonus[r["id"]] = 1.0
        others = [r for r in rows if not by_named(r) and allowed(r)]
        # Only the closest: a playlist "like Metallica" would rather have more of the bands that
        # sound like them than songs by ones that don't.
        similar = recommend(seeds, others, rng.randrange(1, 10**6), size)
        for rank, t in enumerate(similar):
            bonus.setdefault(t["id"], 0.9 * (1 - rank / max(1, len(similar))))
        candidates = [r for r in rows if r["id"] in bonus and (by_named(r) or allowed(r))]
    else:
        candidates = [r for r in rows if allowed(r)]

    # How well each fits the moods and energy asked for (measured songs only).
    feats = moods.features(rows, energy)
    fits = [f for key, _n, _d, _c, f in moods.MOODS if key in want.moods]

    def fit(r) -> float | None:
        s = feats.get(r["id"])
        if s is None:
            return None
        if want.energy == "high" and s.energy < 0.6 or want.energy == "low" and s.energy > 0.4:
            return None
        if fits:
            got = [f(s) for f in fits]
            got = [g for g in got if g is not None]
            return max(got) if got else None
        return s.energy if want.energy == "high" else (1 - s.energy) if want.energy == "low" else 0.0

    top = max(score.values(), default=0) or 1.0
    strict = bool(want.moods or want.energy) and bool(feats)
    scored = []
    for r in candidates:
        f = fit(r)
        if strict and f is None:
            continue
        scored.append((bonus.get(r["id"], 0) + (f or 0) + 0.6 * score.get(r["id"], 0) / top + 0.35 * rng.random(), r))
    scored.sort(key=lambda x: -x[0])

    # Variety first; only if the library is too small for that, more per artist. Named artists
    # never get more than four: a shorter playlist beats one that's mostly the band it's "like".
    picked: list = []
    for cap, named_cap in ((2, 3), (4, 4), (size, 4)):
        per_artist: dict[str, int] = {}
        for r in picked:
            per_artist[artist_of(r)] = per_artist.get(artist_of(r), 0) + 1
        for _s, r in scored:
            if len(picked) >= size:
                break
            if r in picked:
                continue
            a = artist_of(r)
            if per_artist.get(a, 0) >= (named_cap if by_named(r) else cap):
                continue
            per_artist[a] = per_artist.get(a, 0) + 1
            picked.append(r)
        if len(picked) >= size:
            break
    return [r["id"] for r in _spread(picked, artist_of, rng)]


def _spread(songs: list, artist_of, rng: random.Random) -> list:
    """Shuffle, then move songs so the same artist doesn't play twice in a row where avoidable."""
    songs = songs[:]
    rng.shuffle(songs)
    out = []
    while songs:
        last = artist_of(out[-1]) if out else None
        i = next((k for k, r in enumerate(songs) if artist_of(r) != last), 0)
        out.append(songs.pop(i))
    return out
