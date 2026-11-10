"""Listening stats and the yearly Wrapped, from one person's plays.

Everything is worked out in the listener's own time zone (the app sends its offset), so a song
played at 23:30 counts for that evening, not the next morning in UTC. Time listened is the
length of each song played: a play is only counted once a good part of the song is heard.

Periods: "month" (this calendar month), "year" (this year so far), "all", or a year ("2025").
"""

from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict
from typing import Callable

DAY = 86400


def _local(at: float, tz_minutes: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(at + tz_minutes * 60, dt.timezone.utc).replace(tzinfo=None)


def _day(at: float, tz_minutes: int) -> int:
    return int((at + tz_minutes * 60) // DAY)


def streaks(days: set[int], today: int) -> tuple[int, int]:
    """(current, longest) runs of days in a row with something played. Today not played yet
    doesn't end the current streak; yesterday not played does."""
    longest = run = 0
    prev = None
    for d in sorted(days):
        run = run + 1 if prev is not None and d == prev + 1 else 1
        longest = max(longest, run)
        prev = d
    start = today if today in days else today - 1
    current = 0
    while start - current in days:
        current += 1
    return current, longest


def in_period(when: dt.datetime, period: str, now: dt.datetime) -> bool:
    if period == "all":
        return True
    if period == "month":
        return (when.year, when.month) == (now.year, now.month)
    if period == "year":
        return when.year == now.year
    return period.isdigit() and when.year == int(period)


def summary(plays, tracks: dict, genres_of: Callable, tz_minutes: int, period: str, now: float) -> dict:
    """plays: (track_id, played_at), all of this person's. tracks: {id: row}."""
    now_local = _local(now, tz_minutes)
    first_artist_play: dict[str, float] = {}
    days_all: set[int] = set()
    chosen = []
    for tid, at in sorted(plays, key=lambda p: p[1]):
        t = tracks.get(tid)
        if t is None:
            continue
        artist = t["album_artist_name"] or t["artist"]
        first_artist_play.setdefault(artist, at)
        days_all.add(_day(at, tz_minutes))
        if in_period(_local(at, tz_minutes), period, now_local):
            chosen.append((t, at))

    by_song, by_artist, by_album, by_genre = Counter(), Counter(), Counter(), Counter()
    minutes_by_artist: dict[str, float] = defaultdict(float)
    first_song_play: dict[int, float] = {}
    hours, weekdays, by_day = [0] * 24, [0] * 7, Counter()
    for t, at in chosen:
        artist = t["album_artist_name"] or t["artist"]
        by_song[t["id"]] += 1
        first_song_play.setdefault(t["id"], at)
        by_artist[artist] += 1
        minutes_by_artist[artist] += t["duration"] or 0
        by_album[t["album_id"]] += 1
        for g in genres_of(t):
            by_genre[g] += 1
        local = _local(at, tz_minutes)
        hours[local.hour] += 1
        weekdays[local.weekday()] += 1
        by_day[local.date()] += 1

    busiest = min(by_day.items(), key=lambda kv: (-kv[1], kv[0])) if by_day else None
    period_days = {_day(at, tz_minutes) for _t, at in chosen}
    current, _ = streaks(days_all, _day(now, tz_minutes))
    _, longest = streaks(period_days, _day(now, tz_minutes))
    return {
        "period": period,
        "plays": len(chosen),
        "minutes": round(sum(t["duration"] or 0 for t, _ in chosen) / 60),
        "songs": len(by_song),
        "artists": len(by_artist),
        "topArtists": [{"name": a, "plays": n, "minutes": round(minutes_by_artist[a] / 60)}
                       for a, n in sorted(by_artist.items(), key=lambda kv: (-kv[1], -minutes_by_artist[kv[0]], kv[0]))[:10]],
        "topSongs": [{"id": i, "plays": n} for i, n in sorted(by_song.items(), key=lambda kv: (-kv[1], first_song_play[kv[0]]))[:10]],
        "topAlbums": [{"albumId": i, "plays": n} for i, n in by_album.most_common(10)],
        "topGenres": [{"name": g, "plays": n} for g, n in sorted(by_genre.items(), key=lambda kv: (-kv[1], kv[0]))[:5]],
        "hours": hours,
        "weekdays": weekdays,
        "busiestDay": {"date": busiest[0].isoformat(), "plays": busiest[1]} if busiest else None,
        "currentStreak": current,
        "longestStreak": longest,
        "newArtists": [a for a, at in sorted(first_artist_play.items(), key=lambda kv: kv[1])
                       if in_period(_local(at, tz_minutes), period, now_local)],
    }


def on_this_day(plays, tz_minutes: int, now: float) -> list[int]:
    """The songs played on this date a year ago, in the order first played that day."""
    today = _local(now, tz_minutes).date()
    try:
        then = today.replace(year=today.year - 1)
    except ValueError:  # 29 February
        then = today.replace(year=today.year - 1, day=28)
    out: list[int] = []
    for tid, at in sorted(plays, key=lambda p: p[1]):
        if _local(at, tz_minutes).date() == then and tid not in out:
            out.append(tid)
    return out


def years(plays, tz_minutes: int) -> list[int]:
    """The years with plays, newest first (for Wrapped)."""
    return sorted({_local(at, tz_minutes).year for _t, at in plays}, reverse=True)
