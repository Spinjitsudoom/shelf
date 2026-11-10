"""Songs that belong together, going by what people do: the songs that share playlists with
some songs, and the ones played in the same listening sessions (plays less than half an hour
apart, by one person). A small playlist says more about its songs belonging together than a
big one, so each shared group counts for the share of it that the songs make up.

Everyone's playlists and listening on the server count (a score says nothing about who played
what). Worked out from the database and cached until the next play or playlist change.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from .db import session

GAP = 30 * 60  # longer between two plays and it's a new session
SESSION_WEIGHT = 0.6  # a listening session says a little less than a playlist someone made
_cache: dict = {"key": None, "groups": None}
_lock = threading.Lock()


def sessions(plays) -> list[list[int]]:
    """Plays (user, track, played_at) -> each session's songs, in order, without repeats."""
    out: list[list[int]] = []
    last_user, last_at = None, None
    for user, track, at in sorted(plays, key=lambda p: (p[0], p[2])):
        if user != last_user or at - last_at > GAP:
            out.append([])
        if track not in out[-1]:
            out[-1].append(track)
        last_user, last_at = user, at
    return out


def scores(playlists: list[list[int]], sessions_: list[list[int]], seeds: set[int]) -> dict[int, float]:
    """{song: 0..1}: how much each other song belongs with `seeds` (1 = the most)."""
    raw: dict[int, float] = {}
    for groups, weight in ((playlists, 1.0), (sessions_, SESSION_WEIGHT)):
        for g in groups:
            members = set(g)
            hits = len(members & seeds)
            if not hits or len(members) < 2:
                continue
            w = weight * hits / len(members)
            for t in members - seeds:
                raw[t] = raw.get(t, 0.0) + w
    top = max(raw.values(), default=0.0)
    return {t: round(v / top, 4) for t, v in raw.items()} if top else {}


def load(db_path: Path) -> tuple[list[list[int]], list[list[int]]]:
    """(every playlist's songs, the past year's listening sessions), cached."""
    with session(db_path) as conn:
        key = (tuple(conn.execute("SELECT COUNT(*), MAX(id) FROM plays").fetchone()),
               tuple(conn.execute("SELECT COUNT(*), MAX(id) FROM playlist_tracks").fetchone()))
        with _lock:
            if _cache["key"] == key:
                return _cache["groups"]
        by_list: dict[int, list[int]] = {}
        for pid, tid in conn.execute("SELECT playlist_id, track_id FROM playlist_tracks ORDER BY playlist_id, position"):
            by_list.setdefault(pid, []).append(tid)
        plays = conn.execute("SELECT user_id, track_id, played_at FROM plays WHERE played_at > ?",
                             (time.time() - 365 * 86400,)).fetchall()
    groups = (list(by_list.values()), sessions([tuple(p) for p in plays]))
    with _lock:
        _cache.update(key=key, groups=groups)
    return groups
