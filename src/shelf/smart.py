"""Smart playlists: songs picked by rules instead of by hand, and worked out every time the
playlist is opened, so it keeps itself up to date: "not played in 6 months", "under 100 BPM and
in my Favourites", "added this week".

Rules are {"match": "all" | "any", "conditions": [{field, op, value}], "sort", "limit"}. A song
that hasn't been measured yet has no tempo or mood, so it matches no rule about them. A random
order is the same all day (seeded by the day), so the list doesn't change on every look.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from . import credits, genres, moods
from .videos import fold

DAY = 86400
LOSSLESS = ("flac", "alac", "pcm", "wavpack", "ape", "wav", "aiff")

TEXT = {"title", "artist", "album", "genre"}
NUMBER = {"year", "bpm", "duration", "plays"}
DAYS = {"lastPlayed", "added"}
FLAG = {"favourite", "lossless"}
FIELDS = TEXT | NUMBER | DAYS | FLAG | {"mood"}
OPS = {
    **{f: ("is", "isNot", "contains", "notContains") for f in TEXT},
    **{f: ("is", "atLeast", "atMost", "between") for f in NUMBER},
    "added": ("within", "notWithin"),
    "lastPlayed": ("within", "notWithin", "never"),
    **{f: ("is",) for f in FLAG},
    "mood": ("is", "isNot"),
}
SORTS = {
    "artist": None,  # the default: by artist, then album and track
    "title": "title order",
    "added": "newest additions first",
    "lastPlayed": "recently played first",
    "mostPlayed": "most played first",
    "leastPlayed": "least played first",
    "year": "oldest first",
    "bpm": "slowest first",
    "random": "in random order",
}
MOOD_KEYS = {key for key, *_ in moods.MOODS}
MOOD_NAMES = {key: name for key, name, *_ in moods.MOODS}


@dataclass
class Facts:
    """What the rules need beyond the songs themselves, for the person looking."""
    plays: dict[int, int] = field(default_factory=dict)
    last: dict[int, float] = field(default_factory=dict)
    likes: set[int] = field(default_factory=set)
    moods: dict[int, set[str]] = field(default_factory=dict)


def uses_moods(rules: dict) -> bool:
    return any(c["field"] == "mood" for c in rules["conditions"])


# ---------- checking ----------

def _number(v, name: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f"{name} needs a number")
    return v


def validate(rules) -> dict:
    """The rules, checked and tidied; ValueError with a message to show if they don't make sense."""
    if not isinstance(rules, dict):
        raise ValueError("Those rules don’t make sense")
    match = rules.get("match", "all")
    if match not in ("all", "any"):
        raise ValueError("Match all of the rules, or any of them")
    conds = rules.get("conditions") or []
    if not isinstance(conds, list) or len(conds) > 20:
        raise ValueError("Up to 20 rules")
    out = []
    for c in conds:
        if not isinstance(c, dict):
            raise ValueError("Those rules don’t make sense")
        f, op, v = c.get("field"), c.get("op"), c.get("value")
        if f not in FIELDS:
            raise ValueError(f"Shelf can’t pick songs by “{f}”")
        if op not in OPS[f]:
            raise ValueError(f"“{op}” doesn’t work with {f}")
        if f in TEXT:
            if not isinstance(v, str) or not v.strip() or len(v) > 200:
                raise ValueError("Type what to look for")
            v = v.strip()
        elif f in NUMBER:
            if op == "between":
                if not isinstance(v, list) or len(v) != 2:
                    raise ValueError("Between needs two numbers")
                v = sorted(_number(x, f) for x in v)
            else:
                v = _number(v, f)
        elif f in DAYS:
            if op == "never":
                v = None
            else:
                v = int(_number(v, f))
                if not 1 <= v <= 36500:
                    raise ValueError("Pick a number of days from 1 up")
        elif f in FLAG:
            if not isinstance(v, bool):
                raise ValueError(f"{f} is yes or no")
        elif f == "mood":
            if v not in MOOD_KEYS:
                raise ValueError("Pick one of the moods")
        out.append({"field": f, "op": op, "value": v})
    sort = rules.get("sort") or "artist"
    if sort not in SORTS:
        raise ValueError("Pick an order for the songs")
    limit = rules.get("limit")
    if limit is not None:
        limit = int(_number(limit, "The number of songs"))
        if not 1 <= limit <= 5000:
            raise ValueError("Keep between 1 and 5000 songs")
    return {"match": match, "conditions": out, "sort": sort, "limit": limit}


# ---------- picking ----------

def _lossless(codec: str | None) -> bool:
    return (codec or "").lower().startswith(LOSSLESS)


def _text(row, f: str, op: str, want: str) -> bool:
    w = fold(want)
    if f == "genre":
        names = {fold(g) for g in genres.split_tag(row.get("genre"))}
        whole = fold(row.get("genre") or "")
    elif f == "artist":
        names = {fold(n) for n in (credits.names(row["artist"]) or [row["artist"]])}
        names |= {fold(row["artist"]), fold(row.get("album_artist_name") or "")}
        whole = " ".join(sorted(names))
    else:
        value = row["title"] if f == "title" else row.get("album_title") or row.get("album") or ""
        names, whole = {fold(value)}, fold(value)
    hit = w in names if op in ("is", "isNot") else w in whole
    return hit if op in ("is", "contains") else not hit


def _num(value, op: str, want) -> bool:
    if value is None:
        return False
    if op == "is":
        return round(value) == round(want) if isinstance(want, int) else abs(value - want) < 0.5
    if op == "atLeast":
        return value >= want
    if op == "atMost":
        return value <= want
    return want[0] <= value <= want[1]


def _check(row, c: dict, facts: Facts, now: float) -> bool:
    f, op, v = c["field"], c["op"], c["value"]
    tid = row["id"]
    if f in TEXT:
        return _text(row, f, op, v)
    if f == "year":
        return _num(row.get("year"), op, v)
    if f == "bpm":
        return _num(row.get("bpm"), op, v)
    if f == "duration":
        return _num((row.get("duration") or 0) / 60, op, v)
    if f == "plays":
        return _num(facts.plays.get(tid, 0), op, v)
    if f == "favourite":
        return (tid in facts.likes) == v
    if f == "lossless":
        return _lossless(row.get("codec")) == v
    if f == "mood":
        fits = v in facts.moods.get(tid, ())
        return fits if op == "is" else (tid in facts.moods and not fits)  # unmeasured: unknown, so no
    when = facts.last.get(tid) if f == "lastPlayed" else row.get("added_at")
    if op == "never":
        return when is None
    recent = when is not None and now - when <= v * DAY
    return recent if op == "within" else not recent


def songs(rows, facts: Facts, rules: dict, now: float, seed: str = "") -> list[int]:
    """The ids of the songs that fit, in the rules' order, up to the limit."""
    conds, every = rules["conditions"], rules["match"] == "all"
    rows = [dict(r) if not isinstance(r, dict) else r for r in rows]
    hits = [r for r in rows if not conds or (all if every else any)(_check(r, c, facts, now) for c in conds)]
    sort = rules["sort"]
    if sort == "random":
        hits.sort(key=lambda r: r["id"])
        random.Random(seed).shuffle(hits)
    else:
        key = {
            "artist": lambda r: (fold(r.get("album_artist_name") or r["artist"]), r.get("year") or 9999,
                                 fold(r.get("album_title") or ""), r.get("disc_no") or 1, r.get("track_no") or 9999),
            "title": lambda r: (fold(r["title"]),),
            "added": lambda r: (-(r.get("added_at") or 0),),
            "lastPlayed": lambda r: (-(facts.last.get(r["id"]) or 0),),
            "mostPlayed": lambda r: (-facts.plays.get(r["id"], 0), -(facts.last.get(r["id"]) or 0)),
            "leastPlayed": lambda r: (facts.plays.get(r["id"], 0), facts.last.get(r["id"]) or 0),
            "year": lambda r: (r.get("year") or 9999,),
            "bpm": lambda r: (r.get("bpm") or 9999,),
        }[sort]
        hits.sort(key=lambda r: (*key(r), r["id"]))
    ids = [r["id"] for r in hits]
    return ids[:rules["limit"]] if rules["limit"] else ids


def mood_sets(rows, energy: dict[int, float]) -> dict[int, set[str]]:
    """Which moods each measured song fits (empty sets for measured songs that fit none)."""
    out: dict[int, set[str]] = {}
    for tid, s in moods.features(rows, energy).items():
        out[tid] = {key for key, _n, _d, _c, fit in moods.MOODS if fit(s) is not None}
    return out


# ---------- in words ----------

def _span(days: int, last: bool = False) -> str:
    for size, unit in ((365, "year"), (30, "month"), (7, "week"), (1, "day")):
        if days % size == 0:
            n = days // size
            if n == 1:
                return unit if last else f"a {unit}"
            return f"{n} {unit}s"
    return f"{days} days"


def _n(v) -> str:
    return f"{v:g}" if isinstance(v, float) else str(v)


def _range(op: str, v, before: str = "", after: str = "") -> str:
    if op == "between":
        return f"{before}{_n(v[0])}–{_n(v[1])}{after}"
    word = {"is": "", "atLeast": "at least ", "atMost": "at most "}[op]
    return f"{word}{before}{_n(v)}{after}"


def phrase(c: dict) -> str:
    f, op, v = c["field"], c["op"], c["value"]
    q = f"“{v}”" if isinstance(v, str) else ""
    if f in TEXT:
        return {
            "title": {"is": f"called {q}", "isNot": f"not called {q}", "contains": f"with {q} in the title",
                      "notContains": f"without {q} in the title"},
            "artist": {"is": f"by {q}", "isNot": f"not by {q}", "contains": f"by an artist with {q} in the name",
                       "notContains": f"not by an artist with {q} in the name"},
            "album": {"is": f"from the album {q}", "isNot": f"not from the album {q}",
                      "contains": f"from an album with {q} in the name", "notContains": f"not from an album with {q} in the name"},
            "genre": {"is": f"in the genre {q}", "isNot": f"not in the genre {q}", "contains": f"with {q} in the genre",
                      "notContains": f"without {q} in the genre"},
        }[f][op]
    if f == "year":
        return {"is": f"from {v}", "atLeast": f"from {v} or later", "atMost": f"from {v} or earlier"}.get(op) \
            or f"from {_n(v[0])}–{_n(v[1])}"
    if f == "bpm":
        return f"at {_n(v)} BPM" if op == "is" else _range(op, v, after=" BPM") if op != "between" else f"at {_range(op, v)} BPM"
    if f == "duration":
        return f"{_range(op, v)} minutes long"
    if f == "plays":
        if op == "is" and v == 0:
            return "never played"
        return f"played {_range(op, v)} {'time' if v == 1 else 'times'}"
    if f == "favourite":
        return "in your Favourites" if v else "not in your Favourites"
    if f == "lossless":
        return "in lossless quality" if v else "not in lossless quality"
    if f == "mood":
        return f"that fit {MOOD_NAMES[v]}" if op == "is" else f"that don’t fit {MOOD_NAMES[v]}"
    if op == "never":
        return "never played"
    if f == "lastPlayed":
        return f"played in the last {_span(v, last=True)}" if op == "within" else f"not played in {_span(v)}"
    return f"added in the last {_span(v, last=True)}" if op == "within" else f"added more than {_span(v)} ago"


def describe(rules: dict) -> str:
    """The rules as a sentence, for the top of the playlist."""
    parts = [phrase(c) for c in rules["conditions"]]
    text = ("Songs " + f" {'and' if rules['match'] == 'all' else 'or'} ".join(parts)) if parts else "All your songs"
    extra = []
    if rules["limit"]:
        extra.append(f"up to {rules['limit']}")
    if SORTS[rules["sort"]]:
        extra.append(SORTS[rules["sort"]])
    if extra:
        tail = ", ".join(extra)
        text += ". " + tail[0].upper() + tail[1:]
    return text
