"""Library health, for the admin dashboard: albums with no cover or only a small one, gaps in
track numbers, the same song twice (by name, or by its sound: fingerprint.py), songs with no artist, albums whose songs disagree on the
year, lossless files made from an MP3 (lossy.py), and files that couldn't be read. It only reports; nothing in the music folders changes.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Callable

from . import fingerprint, lossy
from .smart import _lossless
from .videos import fold

SMALL = 500  # a cover smaller than this on its longer side looks soft on a big screen
LIMIT = 200  # longest list sent for each kind (the counts are exact)


def _album(r) -> dict:
    return {"id": r["id"], "title": r["title"], "artist": r["artist"]}


def report(conn, cover_size: Callable[[str], tuple[int, int] | None], unreadable: list[str]) -> dict:
    albums = conn.execute("SELECT * FROM albums ORDER BY artist COLLATE NOCASE, title COLLATE NOCASE").fetchall()
    by_key = {a["key"]: a for a in albums}
    tracks = conn.execute("SELECT id, path, title, artist, album_key, track_no, disc_no, duration, codec, bitrate, year,"
                          " cutoff, cutoff_checked, fp_checked"
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

    # The same recording under other names (an untagged copy, a FLAC and an MP3 in different folders),
    # found by its sound. Copies with the same artist and title on different albums are listed above.
    by_id = {t["id"]: t for t in tracks}
    same_audio = []
    for g in fingerprint.stored_groups(conn):
        copies = [by_id[i] for i in g if i in by_id]
        if len(copies) < 2:
            continue
        if len({(fold(c["artist"]), fold(c["title"])) for c in copies}) == 1 and len({c["album_key"] for c in copies}) > 1:
            continue
        best = max(copies, key=lambda c: (_lossless(c["codec"]), c["bitrate"] or 0))
        same_audio.append({"best": best["id"], "copies": [
            {"id": c["id"], "title": c["title"], "artist": c["artist"], "codec": c["codec"], "bitrate": c["bitrate"],
             "album": by_key[c["album_key"]]["title"] if c["album_key"] in by_key else "",
             "albumId": by_key[c["album_key"]]["id"] if c["album_key"] in by_key else None, "path": c["path"]}
            for c in copies]})

    # Lossless files whose sound stops dead where an MP3's or AAC's does: probably made from one.
    lossless = [t for t in tracks if _lossless(t["codec"])]
    fake = [{"id": t["id"], "title": t["title"], "artist": t["artist"], "path": t["path"], "codec": t["codec"],
             "album": by_key[t["album_key"]]["title"] if t["album_key"] in by_key else "",
             "cutoff": round(t["cutoff"]), "likely": lossy.likely_source(t["cutoff"])}
            for t in lossless if t["cutoff_checked"] and lossy.looks_lossy(t["cutoff"])]

    found = {"noCover": no_cover, "smallCover": small, "gaps": gaps, "duplicates": duplicates, "sameAudio": same_audio,
             "noArtist": no_artist, "mixedYears": mixed, "fakeLossless": fake, "unreadable": list(unreadable)}
    return {"counts": {k: len(v) for k, v in found.items()}, **{k: v[:LIMIT] for k, v in found.items()},
            "lossless": {"checked": sum(1 for t in lossless if t["cutoff_checked"]), "total": len(lossless)},
            "fingerprints": {"checked": sum(1 for t in tracks if t["fp_checked"]), "total": len(tracks)}}
