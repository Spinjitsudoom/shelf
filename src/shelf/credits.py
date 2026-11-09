"""Shared credits: "Aerosmith & Yungblud" is two artists, Aerosmith and YUNGBLUD, so the song
shows on both artists' pages instead of making a third artist.

A credit is split on "&", "and", "x", ",", ";", "/", "with", "vs." and "feat.", but only
when it's clearly a collaboration: at least one of the names is an artist in the library on
their own (or the credit says "feat."). So band names like "Earth, Wind & Fire" or
"Simon & Garfunkel" stay whole. Each name takes the spelling the library uses most
("Yungblud" in a shared credit becomes "YUNGBLUD"). Parts in brackets, like
"ELVIS (Original Motion Picture Soundtrack)", are a release note rather than an artist,
so they're left out.

refresh() reads the library's names. Call it after a scan. The rest only reads what refresh
stored, so it's quick to use per song.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from .videos import fold

_SPLIT = re.compile(
    r"\s*[;,]\s*|\s+/\s+|\s+(?:&|and|x|×|vs\.?|with|feat\.?|ft\.?|featuring)\s+", re.I)
_STRONG = re.compile(r"\s(?:feat\.?|ft\.?|featuring)\s", re.I)

_state: dict = {"known": frozenset(), "canon": {}, "cache": {}}


def refresh(conn) -> None:
    """Learn the library's artists: who's credited on their own, and how each is spelled."""
    counts: Counter = Counter()
    for r in conn.execute("SELECT artist, COUNT(*) AS n FROM tracks GROUP BY artist"):
        counts[r["artist"]] += r["n"]
    for r in conn.execute("SELECT artist, track_count FROM albums"):
        counts[r["artist"]] += r["track_count"]
    spellings: dict[str, Counter] = defaultdict(Counter)
    for name, n in counts.items():
        if name and not _SPLIT.search(name):
            spellings[fold(name)][name] += n
    _state.update(known=frozenset(spellings), cache={},
                  canon={f: c.most_common(1)[0][0] for f, c in spellings.items()})


def names(credit: str | None) -> list[str]:
    """The artists in a credit, in order: ["Aerosmith", "YUNGBLUD"] for "Aerosmith & Yungblud"."""
    if not credit:
        return []
    cache = _state["cache"]
    if credit in cache:
        return cache[credit]
    known, canon = _state["known"], _state["canon"]
    parts = [p.strip() for p in _SPLIT.split(credit) if p and p.strip()]
    out: list[str] = []
    if len(parts) > 1 and (_STRONG.search(f" {credit} ") or any(fold(p) in known for p in parts)):
        for p in parts:
            name = canon.get(fold(p), p)
            if "(" not in p and "[" not in p and fold(name) not in {fold(o) for o in out}:
                out.append(name)
    if not out:
        out = [canon.get(fold(credit), credit)]
    if len(cache) < 20000:
        cache[credit] = out
    return out


def credited(credit: str | None, artist: str) -> bool:
    """Whether the artist is one of the names in the credit."""
    want = fold(artist)
    return any(fold(n) == want for n in names(credit))


def display(artist: str) -> str:
    """The library's spelling of an artist's name."""
    return _state["canon"].get(fold(artist), artist)
