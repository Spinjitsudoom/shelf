"""A song's genres: its own genre tag (which may list several: "Metal; Hard Rock"), plus its
artist's genres from MusicBrainz (looked up by the daily new-releases check, see releases.py).

File tags are often missing or loose ("Rock" on a thrash album), and MusicBrainz's genres are
voted on by its editors, so together they find "metal" songs the tags alone would miss. Genres
are compared lowercase with hyphens as spaces: "Hip-Hop" and "hip hop" are the same.
"""

from __future__ import annotations

import re
from functools import lru_cache

from .videos import fold


@lru_cache(maxsize=65536)
def norm(genre: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[-_]", " ", genre or "").lower()).strip()


def split_tag(tag: str | None) -> set[str]:
    """ "Metal; Hard-Rock / Grunge" -> {"metal", "hard rock", "grunge"}."""
    return set(_split(tag or ""))


@lru_cache(maxsize=65536)
def _split(tag: str) -> frozenset[str]:
    return frozenset(n for n in (norm(g) for g in re.split(r"[;/,|]", tag)) if n)


# Songs share a handful of genre tags and artists, so their genres are worked out once each.
_memo: dict = {"key": None, "map": {}}


def song_genres(row, artist_genres: dict[str, list[str]]) -> frozenset[str]:
    key = (row["genre"], row["artist"], row["album_artist_name"])
    sig = (id(artist_genres), len(artist_genres))
    if _memo["key"] != sig:
        _memo.update(key=sig, map={}, ref=artist_genres)  # ref: keeps the id from being reused
    got = _memo["map"].get(key)
    if got is None:
        out = set(_split(row["genre"] or ""))
        for name in (row["artist"], row["album_artist_name"]):
            if name:
                out |= {norm(g) for g in artist_genres.get(fold(name), [])}
        got = frozenset(out)
        if len(_memo["map"]) < 200000:
            _memo["map"][key] = got
    return got


def library_genres(rows, artist_genres: dict[str, list[str]]) -> list[str]:
    """Every genre the library has, by tag or artist, as names to show ("Thrash Metal")."""
    names: dict[str, str] = {}
    for r in rows:
        for g in re.split(r"[;/,|]", r["genre"] or ""):
            if norm(g):
                names.setdefault(norm(g), g.strip())
    for gs in artist_genres.values():
        for g in gs:
            names.setdefault(norm(g), g.title())
    return sorted(names.values(), key=str.lower)
