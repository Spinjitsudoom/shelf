"""A song's genres: its own genre tag (which may list several: "Metal; Hard Rock"), plus its
artist's genres from MusicBrainz (looked up by the daily new-releases check, see releases.py).

File tags are often missing or loose ("Rock" on a thrash album), and MusicBrainz's genres are
voted on by its editors, so together they find "metal" songs the tags alone would miss. Genres
are compared lowercase with hyphens as spaces: "Hip-Hop" and "hip hop" are the same.
"""

from __future__ import annotations

import re

from .videos import fold


def norm(genre: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[-_]", " ", genre or "").lower()).strip()


def split_tag(tag: str | None) -> set[str]:
    """ "Metal; Hard-Rock / Grunge" -> {"metal", "hard rock", "grunge"}."""
    return {norm(g) for g in re.split(r"[;/,|]", tag or "") if norm(g)}


def song_genres(row, artist_genres: dict[str, list[str]]) -> set[str]:
    out = split_tag(row["genre"])
    for name in (row["artist"], row["album_artist_name"]):
        if name:
            out |= {norm(g) for g in artist_genres.get(fold(name), [])}
    return out


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
