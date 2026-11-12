"""Walk the music folders, keep the tracks table in sync, and derive albums from it."""

from __future__ import annotations

import logging
import os
import json
import re
import sqlite3
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import coverfix, covers, credits
from .config import Config
from .db import TRACK_COLUMNS, get_meta, session, set_meta
from .tags import AUDIO_EXTS, read_tags

log = logging.getLogger("shelf.scanner")

_DISC_DIR = re.compile(r"^(cd|disc|disk)[\s._-]*\d+$", re.I)
# Bump when the scanner starts reading something new, so every file gets re-read once.
SCAN_VERSION = "4"  # 4: the less common tags (tags.extras_from) are read too

_UNKNOWN = {"unknown", "[unknown]", "unknown artist", "various", "various artists", "va"}


@dataclass
class ScanResult:
    added: int = 0
    updated: int = 0
    removed: int = 0
    failed: list[str] = field(default_factory=list)
    albums: int = 0
    tracks: int = 0
    seconds: float = 0.0


def album_dir(track_path: Path) -> Path:
    """The folder that represents the album (skipping CD1/Disc 2 style subfolders)."""
    d = track_path.parent
    if _DISC_DIR.match(d.name.strip()):
        d = d.parent
    return d


def album_key(track_path: Path, album: str | None) -> str:
    folder = album_dir(track_path)
    return f"{folder}\x1f{(album or folder.name).casefold()}"


def _root_for(path: Path, roots: list[Path]) -> Path | None:
    for root in roots:
        try:
            path.relative_to(root)
            return root
        except ValueError:
            continue
    return None


def _walk(roots: list[Path]):
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for name in filenames:
                if name.startswith("."):
                    continue
                if os.path.splitext(name)[1].lower() in AUDIO_EXTS:
                    p = Path(dirpath) / name
                    try:
                        st = p.stat()
                    except OSError:
                        continue
                    yield p, st.st_mtime, st.st_size


def scan(cfg: Config, progress=None) -> ScanResult:
    """Incremental scan: only new or modified files get their tags re-read."""
    started = time.time()
    result = ScanResult()
    roots = [r.resolve() for r in cfg.music_dirs]
    live_roots = [r for r in roots if r.is_dir()]
    for r in roots:
        if r not in live_roots:
            log.warning("Music folder %s is missing or unmounted; keeping its tracks", r)

    with session(cfg.db_path) as conn:
        known = {
            row["path"]: (row["id"], row["mtime"], row["size"])
            for row in conn.execute("SELECT id, path, mtime, size FROM tracks")
        }
        full_rescan = get_meta(conn, "scan_version") != SCAN_VERSION
        seen: set[str] = set()
        now = time.time()
        batch = 0
        for path, mtime, size in _walk(live_roots):
            key = str(path)
            seen.add(key)
            prev = known.get(key)
            if prev and prev[1] == mtime and prev[2] == size and not full_rescan:
                continue
            info = read_tags(path)
            if info is None:
                result.failed.append(key)
                continue
            disc_no = info.disc_no
            if disc_no is None and _DISC_DIR.match(path.parent.name.strip()):
                disc_no = int(re.search(r"\d+", path.parent.name).group())
            values = dict(
                path=key, mtime=mtime, size=size, title=info.title, artist=info.artist,
                album_artist=info.album_artist, album=info.album or album_dir(path).name,
                album_key=album_key(path, info.album), track_no=info.track_no,
                disc_no=disc_no, year=info.year, genre=info.genre,
                duration=info.duration, codec=info.codec, mime=info.mime,
                bitrate=info.bitrate, sample_rate=info.sample_rate, bits=info.bits,
                lufs=info.lufs, peak=info.peak, loud_checked=int(info.lufs is not None),
                has_art=int(info.has_art), bpm=None, musical_key=None, rhythm_checked=0, cutoff=None, cutoff_checked=0,
                fp=None, fp_checked=0, extra=json.dumps(info.extra) if info.extra else None,
                added_at=now,
            )
            cols = ", ".join(values)
            marks = ", ".join(f":{k}" for k in values)
            # Loudness from tags wins; otherwise keep an earlier measurement if the audio is unchanged.
            same = "tracks.mtime = excluded.mtime AND tracks.size = excluded.size"
            special = {
                "lufs": f"CASE WHEN excluded.loud_checked = 1 THEN excluded.lufs WHEN {same} THEN tracks.lufs END",
                "peak": f"CASE WHEN excluded.loud_checked = 1 THEN excluded.peak WHEN {same} THEN tracks.peak END",
                "loud_checked": f"CASE WHEN excluded.loud_checked = 1 THEN 1 WHEN {same} THEN tracks.loud_checked ELSE 0 END",
                # tempo and key are measured later; keep them while the audio is unchanged
                "bpm": f"CASE WHEN {same} THEN tracks.bpm END",
                "musical_key": f"CASE WHEN {same} THEN tracks.musical_key END",
                "rhythm_checked": f"CASE WHEN {same} THEN tracks.rhythm_checked ELSE 0 END",
                "cutoff": f"CASE WHEN {same} THEN tracks.cutoff END",
                "cutoff_checked": f"CASE WHEN {same} THEN tracks.cutoff_checked ELSE 0 END",
                "fp": f"CASE WHEN {same} THEN tracks.fp END",
                "fp_checked": f"CASE WHEN {same} THEN tracks.fp_checked ELSE 0 END",
            }
            updates = ", ".join(
                f"{k} = {special.get(k, f'excluded.{k}')}" for k in values if k not in ("path", "added_at")
            )
            conn.execute(
                f"INSERT INTO tracks ({cols}) VALUES ({marks}) "
                f"ON CONFLICT(path) DO UPDATE SET {updates}",
                values,
            )
            if prev:
                result.updated += 1
            else:
                result.added += 1
            batch += 1
            if batch % 200 == 0:
                conn.commit()
                if progress:
                    progress(result.added + result.updated)

        # Remove tracks that vanished, but only under folders that are actually mounted,
        # so an unplugged drive doesn't wipe its part of the library. Tracks outside every
        # music folder (one taken out of the library) go too.
        gone = [
            (tid,) for path, (tid, _, _) in known.items()
            if path not in seen and (_root_for(Path(path), live_roots) is not None or _root_for(Path(path), roots) is None)
        ]
        if gone:
            conn.executemany("DELETE FROM tracks WHERE id = ?", gone)
            result.removed = len(gone)

        rebuild_albums(conn, roots, cfg.found_cover_dir)
        result.tracks = conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
        result.albums = conn.execute("SELECT COUNT(*) FROM albums").fetchone()[0]
        set_meta(conn, "last_scan", str(time.time()))
        set_meta(conn, "scan_version", SCAN_VERSION)

    result.seconds = round(time.time() - started, 2)
    return result


def _pick_album_artist(rows: list[sqlite3.Row], roots: list[Path]) -> str:
    tagged = Counter(r["album_artist"] for r in rows if r["album_artist"])
    if tagged:
        return tagged.most_common(1)[0][0]
    # Library laid out as <root>/<Artist>/<Album>/<tracks>: trust the artist folder.
    first = Path(rows[0]["path"])
    root = _root_for(first, roots)
    if root is not None:
        parts = album_dir(first).relative_to(root).parts
        if len(parts) >= 2 and parts[0].casefold() not in _UNKNOWN:
            return parts[0]
    artists = Counter(r["artist"] for r in rows)
    top, n = artists.most_common(1)[0]
    if n == len(rows) or len(artists) == 1:
        return top
    return "Various Artists"


def _pick_cover(rows: list[sqlite3.Row], found_dir: Path | None = None, key: str | None = None) -> str | None:
    """A cover found for the album in the admin dashboard (coverfix.py) wins; then an image in
    the album's folder; then art inside the files."""
    if found_dir is not None and key is not None:
        found = coverfix.override_path(found_dir, key)
        if found.is_file():
            return f"file:{found}"
    first = Path(rows[0]["path"])
    folder_img = covers.find_folder_image(first.parent) or covers.find_folder_image(album_dir(first))
    if folder_img:
        return f"file:{folder_img}"
    with_art = next((r for r in rows if r["has_art"]), None)
    return f"embedded:{with_art['path']}" if with_art else None


_ALBUM_EXTRAS = ("album_mbid", "album_sort", "compilation", "release_types", "labels", "original_year")


def album_extra(tracks: list[sqlite3.Row]) -> str | None:
    """An album's share of its songs' less common tags: the MusicBrainz release, labels, release
    type... from the first song that has each; explicit if any song is."""
    out: dict = {}
    for t in tracks:
        try:
            got = json.loads(t["extra"] or "{}")
        except (TypeError, ValueError, IndexError, KeyError):
            continue
        for k in _ALBUM_EXTRAS:
            if k in got and k not in out:
                out[k] = got[k]
        if got.get("explicit") == "explicit" or (got.get("explicit") == "clean" and "explicit" not in out):
            out["explicit"] = got["explicit"]
    return json.dumps(out) if out else None


def rebuild_albums(conn: sqlite3.Connection, roots: list[Path], found_dir: Path | None = None) -> None:
    rows = conn.execute(
        f"SELECT {TRACK_COLUMNS} FROM tracks ORDER BY album_key, COALESCE(disc_no, 1), COALESCE(track_no, 9999), path"
    ).fetchall()
    groups: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        groups.setdefault(r["album_key"], []).append(r)

    existing = {
        r["key"]: (r["cover_src"], r["color"])
        for r in conn.execute("SELECT key, cover_src, color FROM albums")
    }
    # Pick one spelling per artist ("YUNGBLUD" vs "Yungblud") weighted by track count.
    chosen = {key: _pick_album_artist(tracks, roots) for key, tracks in groups.items()}
    spellings: dict[str, Counter] = {}
    for key, name in chosen.items():
        spellings.setdefault(name.casefold(), Counter())[name] += len(groups[key])
    canonical = {fold: c.most_common(1)[0][0] for fold, c in spellings.items()}

    for key, tracks in groups.items():
        titles = Counter(t["album"] for t in tracks)
        years = Counter(t["year"] for t in tracks if t["year"])
        genres = Counter(t["genre"] for t in tracks if t["genre"])
        cover_src = _pick_cover(tracks, found_dir, key)
        extra = album_extra(tracks)
        old_cover, old_color = existing.get(key, (None, None))
        color = old_color if old_cover == cover_src else None
        conn.execute(
            """
            INSERT INTO albums (key, title, artist, year, genre, track_count, duration, cover_src, color, added_at, extra)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                title = excluded.title, artist = excluded.artist, year = excluded.year,
                genre = excluded.genre, track_count = excluded.track_count,
                duration = excluded.duration, cover_src = excluded.cover_src,
                color = excluded.color, added_at = excluded.added_at, extra = excluded.extra
            """,
            (
                key,
                titles.most_common(1)[0][0],
                canonical[chosen[key].casefold()],
                years.most_common(1)[0][0] if years else None,
                genres.most_common(1)[0][0] if genres else None,
                len(tracks),
                sum(t["duration"] for t in tracks),
                cover_src,
                color,
                min(t["added_at"] for t in tracks),
                extra,
            ),
        )
    stale = [(k,) for k in existing if k not in groups]
    if stale:
        conn.executemany("DELETE FROM albums WHERE key = ?", stale)
    credits.refresh(conn)


def warm_covers(cfg: Config) -> int:
    """Pre-render grid thumbnails and pick accent colors for albums that lack one."""
    with session(cfg.db_path) as conn:
        todo = conn.execute(
            "SELECT id, cover_src FROM albums WHERE color IS NULL"
        ).fetchall()
    done = 0
    for row in todo:
        color = ""
        if row["cover_src"]:
            thumb = covers.get_cover(cfg.cover_dir, row["cover_src"], 320)
            if thumb:
                color = covers.accent_color(thumb) or ""
        with session(cfg.db_path) as conn:
            conn.execute("UPDATE albums SET color = ? WHERE id = ?", (color, row["id"]))
        done += 1
    return done
