"""Search that forgives: a spelling mistake still finds the song, and a band's nickname finds
the band.

Each word of a search keeps matching as it always did (anywhere in a title, artist or album),
and may bring along:

- Spellings. A word that's nowhere in the library ("sevenfould") also looks for the library's
  words closest to it ("sevenfold"): at most one letter off for short words, two for longer
  ones, where a swapped pair counts as one (Damerau–Levenshtein). The close words are found
  without comparing against every word, by "symmetric delete" (as in SymSpell): each library
  word is filed under itself and every way of dropping one of its letters, and a search word
  looks itself up the same way.
- Nicknames, matched against artists only: a band's initials (MCR for My Chemical Romance,
  at least three letters), its name run together (ACDC for AC/DC), and the other names
  MusicBrainz knows it by (A7X for Avenged Sevenfold), which releases.py fetches along with
  the artist's genres when artist info is on.

The index is built from the library on the first search after a scan, and kept until the next.
Plain matches sort before the ones found this way.
"""

from __future__ import annotations

import json
import logging
import threading
from array import array
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import credits
from .db import get_meta, session
from .videos import fold

log = logging.getLogger("shelf.fuzzy")

MIN_WORD = 4  # shorter words aren't corrected: too many real words are one letter apart
MAX_SPELLINGS = 3


def squash(s: str) -> str:
    return fold(s).replace(" ", "")


def distance(a: str, b: str, limit: int) -> int:
    """Damerau–Levenshtein (optimal string alignment) distance, or limit + 1 once it's over."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev2: list[int] = []
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = a[i - 1] != b[j - 1]
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        if min(cur) > limit:
            return limit + 1
        prev2, prev = prev, cur
    return prev[-1]


def allowed(word: str) -> int:
    return 1 if len(word) < 6 else 2


def _deletes(word: str) -> set[str]:
    return {word[:i] + word[i + 1:] for i in range(len(word))}


def nicknames(name: str) -> set[str]:
    """The short ways of writing an artist's name: initials and the name run together."""
    words = fold(name).split()
    out: set[str] = set()
    if len(words) >= 2:
        out.add("".join(words))
        for ws in (words, words[1:] if words[0] == "the" else []):
            initials = "".join(w[0] for w in ws)
            if len(ws) >= 2 and len(initials) >= 3:
                out.add(initials)
    return out


@dataclass
class Match:
    """One word of a search and what else it stands for."""
    term: str
    spellings: list[str] = field(default_factory=list)  # library words it's probably a misspelling of
    artists: list[str] = field(default_factory=list)  # artists it's a nickname of

    @property
    def plain(self) -> bool:
        return not self.spellings and not self.artists

    def found_in(self, text: str) -> bool:
        """Whether this word (or what it stands for) is in a name. `text` is folded."""
        return any(w and w in text for w in [fold(self.term), *self.spellings, *map(fold, self.artists)])


class Index:
    def __init__(self, artists: list[str], words: Counter, aliases: dict[str, list[str]]):
        self.counts = words
        self.blob = "\x1f" + "\x1f".join(words) + "\x1f"
        # Each word filed under itself and each one-letter-shorter form, by hash, in two sorted
        # arrays (a few MB even for a huge library). A clash of hashes only brings up a word
        # that the distance check then turns away.
        self.words = [w for w in words if len(w) >= MIN_WORD and w.isalpha()]
        keys, ids = array("q"), array("i")
        for i, w in enumerate(self.words):
            hs = {hash(d) for d in _deletes(w)} | {hash(w)}
            keys.extend(hs)
            ids.extend([i] * len(hs))
        k = np.frombuffer(keys, dtype=np.int64)
        by = np.argsort(k, kind="stable")
        self.keys, self.ids = k[by], np.frombuffer(ids, dtype=np.int32)[by]
        self.nick: dict[str, set[str]] = {}
        by_fold: dict[str, str] = {}
        for credit in artists:
            for name in credits.names(credit):
                by_fold.setdefault(fold(name), name)
        for key, name in by_fold.items():
            for n in nicknames(name) | {squash(a) for a in aliases.get(key, [])}:
                if n:
                    self.nick.setdefault(n, set()).add(name)

    def spellings(self, word: str) -> list[str]:
        """The library's words this word is probably a misspelling of (none if it's in the library)."""
        if len(word) < MIN_WORD or not word.isalpha() or word in self.blob:
            return []
        limit = allowed(word)
        want = np.array([hash(k) for k in _deletes(word) | {word}], dtype=np.int64)
        lo, hi = np.searchsorted(self.keys, want, "left"), np.searchsorted(self.keys, want, "right")
        seen = {int(i) for a, b in zip(lo, hi) if b > a for i in self.ids[a:b]}
        scored = sorted((d, -self.counts[w], w) for w in map(self.words.__getitem__, seen)
                        if (d := distance(word, w, limit)) <= limit)
        return [w for _, _, w in scored[:MAX_SPELLINGS]]

    def match(self, term: str) -> Match:
        words = fold(term).split()
        spellings = self.spellings(words[0]) if len(words) == 1 else []
        return Match(term, spellings, sorted(self.nick.get(squash(term), ())))


_lock = threading.Lock()
_cache: dict[str, tuple[tuple, Index]] = {}
_building: set[str] = set()


def _build(conn) -> Index:
    artists = [r[0] for r in conn.execute(
        "SELECT artist FROM albums UNION SELECT artist FROM tracks "
        "UNION SELECT album_artist FROM tracks WHERE album_artist IS NOT NULL") if r[0]]
    words: Counter = Counter()
    for (s,) in conn.execute("SELECT title FROM tracks UNION ALL SELECT title FROM albums"):
        words.update(fold(s).split())
    for a in artists:
        words.update(fold(a).split())
    known = json.loads(get_meta(conn, "mb_artist_genres") or "{}")
    aliases = {k: v.get("aliases") or [] for k, v in known.items() if isinstance(v, dict)}
    return Index(artists, words, aliases)


def _version(conn) -> tuple:
    return get_meta(conn, "last_scan"), get_meta(conn, "releases_checked")


def index(conn, wait: bool = False) -> Index:
    """The library's search index. It's rebuilt after each scan (and each MusicBrainz check);
    meanwhile searches use the one before, so nobody waits on a big library's rebuild."""
    version = _version(conn)
    where = conn.execute("PRAGMA database_list").fetchone()[2]
    with _lock:
        hit = _cache.get(where)
        if hit and hit[0] == version:
            return hit[1]
        rebuild = hit is not None and not wait and where not in _building
        if rebuild:
            _building.add(where)
    if rebuild:
        def run():
            try:
                with session(Path(where)) as c:
                    v = _version(c)
                    built = _build(c)
                with _lock:
                    _cache[where] = (v, built)
            except Exception:
                log.exception("Rebuilding the search index failed")
            finally:
                with _lock:
                    _building.discard(where)
        threading.Thread(target=run, name="shelf-search-index", daemon=True).start()
        return hit[1]
    if hit is not None and not wait:
        return hit[1]  # being rebuilt
    built = _build(conn)
    with _lock:
        _cache[where] = (version, built)
    return built


def matches(conn, q: str, limit: int = 6) -> list[Match]:
    """The words of a search, each with what else it stands for."""
    terms = [t for t in q.split() if t][:limit]
    if not terms:
        return []
    ix = index(conn)
    return [ix.match(t) for t in terms]


def _like(s: str) -> str:
    return "%" + s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def where(ms: list[Match], cols: list[str], artist_cols: list[str] | None = None,
          plain_only: bool = False) -> tuple[str, list]:
    """SQL for rows matching every word: the word (or a spelling of it) in any of `cols`, or
    an artist it's a nickname of in `artist_cols` (by default the columns named like artists)."""
    if artist_cols is None:
        artist_cols = [c for c in cols if c.split(".")[-1] == "artist"]
    clauses, params = [], []
    for m in ms:
        ors = []
        for w in [m.term] + ([] if plain_only else m.spellings):
            ors += [f"{c} LIKE ? ESCAPE '\\'" for c in cols]
            params += [_like(w)] * len(cols)
        if not plain_only:
            for name in m.artists:
                ors += [f"{c} LIKE ? ESCAPE '\\'" for c in artist_cols]
                params += [_like(name)] * len(artist_cols)
        clauses.append("(" + " OR ".join(ors) + ")")
    return " AND ".join(clauses), params


def order(ms: list[Match], cols: list[str]) -> tuple[str, list]:
    """An ORDER BY part that puts plain matches first ("" when nothing was found another way)."""
    if all(m.plain for m in ms):
        return "", []
    w, p = where(ms, cols, plain_only=True)
    return f"({w}) DESC, ", p
