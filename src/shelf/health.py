"""Library health, for the admin dashboard: albums with no cover or only a small one, gaps in
track numbers, the same song twice, songs with no artist, albums whose songs disagree on the
year, and files that couldn't be read. It only reports; nothing in the music folders changes.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Callable

from .smart import _lossless
from .videos import fold

SMALL = 500  # a cover smaller than this on its longer side looks soft on a big screen
LIMIT = 200  # longest list sent for each kind (the counts are exact)


def _album(r) -> dict:
    return {"id": r["id"], "title": r["title"], "artist": r["artist"]}


def report(conn, cover_size: Callable[[str], tuple[int, int] | None], unreadable: list[str]) -> dict:
    albums = conn.execute("SELECT * FROM albums ORDER BY artist COLLATE NOCASE, title COLLATE NOCASE").fetchall()
    by_key = {a["key"]: a for a in albums}
    tracks = conn.execute("SELECT id, path, title, artist, album_key, track_no, disc_no, duration, codec, bitrate, year"
                          " FROM tracks ORDER BY album_key, COALESCE(disc_no, 1), COALESCE(track_no, 9999)").fetchall()

    no_cover, small = [], []
    for a in albums:
        if not a["cover_src"]:
            no_cover.append(_album(a))
            continue
        size = cover_size(a["cover_src"])
        if size and max(size) < SMALL:
            small.append({**_album(a), "size": list(size)})

    per_album: dict[str, list] = defaultdict(list)
    for t in tracks:
        per_album[t["album_key"]].append(t)

    gaps, mixed = [], []
    for key, ts in per_album.items():
        a = by_key.get(key)
        if not a:
            continue
        discs: dict[int, set[int]] = defaultdict(set)
        for t in ts:
            if t["track_no"]:
                discs[t["disc_no"] or 1].add(t["track_no"])
        for disc, nums in sorted(discs.items()):
            missing = sorted(set(range(1, max(nums) + 1)) - nums)
            if missing:
                gaps.append({**_album(a), "disc": disc, "missing": missing[:50]})
        years = sorted({t["year"] for t in ts if t["year"]})
        if len(years) > 1:
            mixed.append({**_album(a), "years": years})

    no_artist = [{"id": t["id"], "title": t["title"], "path": t["path"]} for t in tracks if fold(t["artist"]) == "unknown artist"]

    # The same song (artist and title) on different albums, within 2 seconds of each other.
    songs: dict[tuple[str, str], list] = defaultdict(list)
    for t in tracks:
        songs[(fold(t["artist"]), fold(t["title"]))].append(t)
    duplicates = []
    for group in songs.values():
        if len(group) < 2:
            continue
        group = sorted(group, key=lambda t: t["duration"] or 0)
        cluster = [group[0]]
        for t in group[1:] + [None]:
            if t is not None and abs((t["duration"] or 0) - (cluster[-1]["duration"] or 0)) <= 2:
                cluster.append(t)
                continue
            if len({c["album_key"] for c in cluster}) > 1:
                best = max(cluster, key=lambda c: (_lossless(c["codec"]), c["bitrate"] or 0))
                duplicates.append({
                    "title": cluster[0]["title"], "artist": cluster[0]["artist"], "best": best["id"],
                    "copies": [{"id": c["id"], "album": by_key[c["album_key"]]["title"] if c["album_key"] in by_key else "",
                                "albumId": by_key[c["album_key"]]["id"] if c["album_key"] in by_key else None,
                                "codec": c["codec"], "bitrate": c["bitrate"], "path": c["path"]} for c in cluster],
                })
            cluster = [t] if t is not None else []

    found = {"noCover": no_cover, "smallCover": small, "gaps": gaps, "duplicates": duplicates,
             "noArtist": no_artist, "mixedYears": mixed, "unreadable": list(unreadable)}
    return {"counts": {k: len(v) for k, v in found.items()}, **{k: v[:LIMIT] for k, v in found.items()}}
