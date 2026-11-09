"""Made for you: Shelf Mixes, On Repeat, Rediscover and Discover, built from one person's
listening and likes, plus song and artist radio.

Everything is worked out from the library and that person's plays when asked, with a seed for
the day (or week), so a mix stays the same all day and changes the next.

Shelf Mixes: the artists someone plays most are grouped with artists that share their genre,
up to six groups. Each mix is about 60% songs by its artists (favourites and ones not played
much) and 40% songs from elsewhere in the library that fit them (artists, genres, tempos and
keys, by the same scoring as playlist recommendations), ordered so an artist doesn't repeat
back to back.
"""

from __future__ import annotations

import random
import time
from collections import Counter, defaultdict
from typing import Callable

from .videos import fold

DAY = 86400
MIX_SIZE = 40
LIST_SIZE = 30
MAX_DAILY = 6
# A colour for each Shelf Mix's cover band.
COLORS = ["#e8590c", "#2f9e44", "#1c7ed6", "#c2255c", "#7048e8", "#e0a800"]

Recommend = Callable[[list, list, int, int], list]


def artist_of(t) -> str:
    return t["album_artist_name"] or t["artist"]


def affinity(plays: list, liked: set[int], now: float) -> dict[int, float]:
    """How much someone likes each song: plays, recent ones counting more (a 30-day
    half-life), and a like worth a few plays."""
    score: dict[int, float] = defaultdict(float)
    for tid, at in plays:
        score[tid] += 0.5 ** ((now - at) / (30 * DAY))
    for tid in liked:
        score[tid] += 2.0
    return score


def _names(artists: list[str]) -> str:
    if len(artists) == 1:
        return f"{artists[0]} and more"
    if len(artists) == 2:
        return f"{artists[0]}, {artists[1]} and more"
    return f"{artists[0]}, {artists[1]} and {artists[2]}"


def daily_mixes(tracks: list, score: dict[int, float], recommend: Recommend, seed: str) -> list[dict]:
    by_artist: dict[str, list] = defaultdict(list)
    display: dict[str, str] = {}
    for t in tracks:
        key = fold(artist_of(t))
        by_artist[key].append(t)
        display.setdefault(key, artist_of(t))
    weight = {a: sum(score.get(t["id"], 0) for t in ts) for a, ts in by_artist.items()}
    history = sum(weight.values()) >= 3
    if not history:  # someone new: their library is the starting point
        weight = {a: len(ts) / 100 for a, ts in by_artist.items()}
    genre = {a: Counter(fold(t["genre"]) for t in ts if t["genre"]).most_common(1) for a, ts in by_artist.items()}
    genre = {a: g[0][0] if g else "" for a, g in genre.items()}

    ranked = [a for a in sorted(weight, key=lambda a: -weight[a]) if weight[a] > 0]
    groups: list[list[str]] = []
    used: set[str] = set()
    for a in ranked:
        if a in used or len(groups) >= MAX_DAILY:
            continue
        group = [a]
        used.add(a)
        # Up to two more artists in the same genre, the most played first.
        for b in ranked:
            if len(group) >= 3:
                break
            if b not in used and genre[a] and genre[b] == genre[a]:
                group.append(b)
                used.add(b)
        if sum(len(by_artist[x]) for x in group) >= 8:
            groups.append(group)

    mixes = []
    for i, group in enumerate(groups):
        rng = random.Random(f"{seed}:daily:{i}")
        own = [t for a in group for t in by_artist[a]]
        # Favourites first in line, but songs not played much get their turn too.
        own.sort(key=lambda t: -(score.get(t["id"], 0) + rng.random() * 0.8))
        n_own = min(len(own), round(MIX_SIZE * 0.6))
        picked = own[:n_own]
        ids = {t["id"] for t in picked}
        favourites = sorted(own, key=lambda t: -score.get(t["id"], 0))[:25]
        pool = [t for t in tracks if t["id"] not in ids and fold(artist_of(t)) not in group]
        others = recommend(favourites, pool, rng.randrange(1, 10**6), MIX_SIZE - len(picked))
        names = [display[a] for a in group]
        mixes.append({
            "key": f"daily-{i + 1}",
            "kind": "daily",
            "name": f"Shelf Mix {i + 1}",
            "description": _names(names),
            "artists": names,
            "color": COLORS[i % len(COLORS)],
            "_own": picked,
            "_others": others,
            "_rng": rng,
        })
    return mixes


def finish_daily(mix: dict, track_json) -> list[dict]:
    """The songs of a Shelf Mix in play order, as JSON, with the recommended ones mixed in."""
    rng: random.Random = mix["_rng"]
    own = [track_json(t) for t in mix["_own"]]
    others = list(mix["_others"])  # already JSON
    allt = own + others
    rng.shuffle(allt)
    out, rest = [], allt
    while rest:
        prev = fold(out[-1]["albumArtist"] or out[-1]["artist"]) if out else None
        i = next((k for k, t in enumerate(rest) if fold(t["albumArtist"] or t["artist"]) != prev), 0)
        out.append(rest.pop(i))
    return out


def on_repeat(tracks_by_id: dict, plays: list, now: float) -> list:
    """Songs played most over the last month (at least twice)."""
    n = Counter(tid for tid, at in plays if at > now - 30 * DAY)
    return [tracks_by_id[t] for t, c in n.most_common() if c >= 2 and t in tracks_by_id][:LIST_SIZE]


def rediscover(tracks_by_id: dict, plays: list, now: float) -> list:
    """Songs played a lot before, but not for the last six weeks."""
    old = Counter(tid for tid, at in plays if at < now - 60 * DAY)
    recent = {tid for tid, at in plays if at > now - 45 * DAY}
    return [tracks_by_id[t] for t, c in old.most_common() if c >= 2 and t not in recent and t in tracks_by_id][:LIST_SIZE]


def discover(tracks: list, plays: list, score: dict[int, float], recommend: Recommend, seed: str) -> list:
    """Songs from the library never played, that fit what's played most."""
    played = {tid for tid, _ in plays}
    favourites = sorted((t for t in tracks if score.get(t["id"])), key=lambda t: -score[t["id"]])[:50]
    if len(favourites) < 3:
        return []
    pool = [t for t in tracks if t["id"] not in played]
    return recommend(favourites, pool, random.Random(f"{seed}:discover").randrange(1, 10**6), LIST_SIZE)


def week_seed(uid: int, now: float) -> str:
    return f"{uid}:w{int(now // (7 * DAY))}"


def day_seed(uid: int, now: float) -> str:
    # The day turns over at 4 a.m. server time.
    local = time.localtime(now - 4 * 3600)
    return f"{uid}:{local.tm_year}-{local.tm_yday}"



def blend(tracks: list, mine: dict[int, float], theirs: dict[int, float], recommend: Recommend, seed: str) -> dict:
    """Two people's tastes in one list: songs you both play, each one's favourites, and songs
    that fit you both. `match` is how alike the artists you play are, 0 to 100."""
    by_id = {t["id"]: t for t in tracks}

    def artist_weights(score):
        w: dict[str, float] = defaultdict(float)
        for tid, v in score.items():
            if tid in by_id:
                w[fold(artist_of(by_id[tid]))] += v
        return w

    a, b = artist_weights(mine), artist_weights(theirs)
    na = sum(v * v for v in a.values()) ** 0.5
    nb = sum(v * v for v in b.values()) ** 0.5
    match = round(100 * sum(v * b.get(k, 0) for k, v in a.items()) / (na * nb)) if na and nb else 0

    rng = random.Random(f"{seed}:blend")
    top = lambda score: [tid for tid, _ in sorted(score.items(), key=lambda x: -(x[1] + rng.random() * 0.5)) if tid in by_id]
    both = sorted((tid for tid in mine if tid in theirs and tid in by_id), key=lambda t: -min(mine[t], theirs[t]))
    picks: list[tuple[object, str]] = [(by_id[t], "both") for t in both[:12]]
    taken = {t for t in both[:12]}
    for who, score in (("you", mine), ("them", theirs)):
        for tid in top(score):
            if len([1 for _, w in picks if w == who]) >= 14:
                break
            if tid not in taken:
                picks.append((by_id[tid], who))
                taken.add(tid)
    favourites = [by_id[t] for t in (top(mine)[:20] + top(theirs)[:20])]
    if favourites:
        pool = [t for t in tracks if t["id"] not in taken]
        for t in recommend(favourites, pool, rng.randrange(1, 10**6), 10):
            picks.append((t, "both"))
    rng.shuffle(picks)
    # No score until both have played something: 0% would just mean "no history yet".
    return {"match": max(0, min(100, match)) if a and b else None, "tracks": picks}
