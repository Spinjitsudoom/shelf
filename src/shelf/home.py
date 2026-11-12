"""Home, shaped by what you like. Classic arithmetic, no AI:

- **Taste**: how much you like each artist: your plays (recent ones counting more, a 30-day
  half-life) and likes, added up per artist, plus a bonus for the artists you follow.
- **More like …**: two of your favourite artists (a different pair from your top few each day),
  each with albums by other artists the recommender says fit them (sound, genre, tempo, key,
  shared playlists).
- **From artists you follow**: their albums, the newly added first, then the ones you've
  played least.
- **The order of the rows** learns from use: each row starts with a base weight, and each time
  you come back to open something from it (once per half hour at most), it climbs (two-week
  half-life), so rows you never touch sink.
"""

from __future__ import annotations

import random
from collections import defaultdict

from . import credits, mixes
from .videos import fold

DAY = 86400
FOLLOW_BONUS = 3.0          # a followed artist counts like a few recent plays
LIKE_ROWS = 2
ROW_ALBUMS = 14
TAP_HALF_LIFE = 14 * DAY
TAP_GAP = 30 * 60           # uses of one row closer together than this count once
TAP_WEIGHT = 8.0
TAP_CAP = 60.0          # a row used all the time can climb above every other

# Where each row starts before your use moves it: higher comes first.
BASE = {"mixes": 60, "following": 50, "like": 45, "recent": 40, "podcasts": 35, "added": 30, "top": 25, "releases": 20, "rediscover": 10}


def kind(key: str) -> str:
    """'like:Green Day' and 'like:Burial' are both 'like' rows."""
    return key.split(":", 1)[0]


def artist_taste(tracks: list, score: dict[int, float], follows: set[str]) -> dict[str, tuple[str, float]]:
    """Folded artist name -> (display name, how much you like them)."""
    out: dict[str, list] = {}
    for t in tracks:
        s = score.get(t["id"], 0.0)
        if not s:
            continue
        for name in credits.names(mixes.artist_of(t)):
            entry = out.setdefault(fold(name), [name, 0.0])
            entry[1] += s
    for key in follows:
        if key in out:
            out[key][1] += FOLLOW_BONUS
    # Followed artists you haven't played yet still count.
    for t in tracks:
        for name in credits.names(mixes.artist_of(t)):
            k = fold(name)
            if k in follows and k not in out:
                out[k] = [name, FOLLOW_BONUS]
    return {k: (v[0], v[1]) for k, v in out.items()}


def seed_artists(taste: dict[str, tuple[str, float]], seed: str, n: int = LIKE_ROWS) -> list[str]:
    """`n` of your top four artists (a different pair each day), best liked first."""
    top = sorted(taste.values(), key=lambda v: -v[1])[:4]
    if len(top) <= n:
        return [name for name, _ in top]
    picked = random.Random(seed).sample(top, n)
    return [name for name, _ in sorted(picked, key=lambda v: -v[1])]


def like_albums(picks: list[dict], artist: str, limit: int = ROW_ALBUMS) -> list[int]:
    """Album ids from recommended songs, in the order they first come up, leaving out the
    artist's own albums."""
    out: list[int] = []
    for t in picks:
        if t["albumId"] in out or credits.credited(t.get("albumArtist") or t["artist"], artist):
            continue
        out.append(t["albumId"])
        if len(out) >= limit:
            break
    return out


def following_albums(albums: list, follows: set[str], plays: dict[str, int], now: float,
                     limit: int = ROW_ALBUMS) -> list:
    """Albums by artists you follow: added in the last month first (newest first), then the
    ones you've played least."""
    mine = [a for a in albums if any(fold(n) in follows for n in credits.names(a["artist"]))]
    month = now - 30 * DAY
    fresh = sorted((a for a in mine if a["added_at"] >= month), key=lambda a: -a["added_at"])
    rest = sorted((a for a in mine if a["added_at"] < month), key=lambda a: (plays.get(a["key"], 0), -a["added_at"]))
    return (fresh + rest)[:limit]


def tap_scores(taps: list[tuple[str, float]], now: float) -> dict[str, float]:
    """How much each kind of row has been used lately."""
    out: dict[str, float] = defaultdict(float)
    for row, at in taps:
        out[kind(row)] += 0.5 ** (max(0.0, now - at) / TAP_HALF_LIFE)
    return out


def order(keys: list[str], used: dict[str, float], new_listener: bool) -> list[str]:
    """The rows in the order to show them."""
    def weight(i_key):
        i, key = i_key
        k = kind(key)
        w = BASE.get(k, 0)
        if k == "like":  # the second "More like" row sits a little lower than the first
            w -= 8 * sum(1 for other in keys[:i] if kind(other) == "like")
        if new_listener and k == "added":
            w += 18  # little listening yet: what’s on the shelf matters more (still under who you follow)
        return w + min(TAP_CAP, TAP_WEIGHT * used.get(k, 0.0))
    return [key for _, key in sorted(enumerate(keys), key=lambda ik: (-weight(ik), ik[0]))]
