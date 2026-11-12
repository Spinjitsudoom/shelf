"""The same recording twice, found by its sound, for Library health.

Library health already lists the same artist and title twice. This finds copies whatever they're
called: an untagged file, a FLAC and an MP3 of one song in different folders, a rip that starts
with a second of silence. Each song's first minute gets an audio fingerprint (Chromaprint, through
ffmpeg, which every Shelf install has): about eight 32-bit numbers a second, each describing the
sound at that moment. Two encodes of one recording print nearly the same numbers (a few bits in
a hundred differ); another mix of the same song differs in about a tenth, a different song in half.

Finding pairs without comparing every song with every other: songs that share some of the exact
numbers, at a steady distance apart (the offset, when one starts later), are compared bit by bit
at that offset. Numbers that many songs share (silence, a click track) say nothing and are left out.
The same sound but a different length (a radio edit, an extended mix) isn't the same recording.

Fingerprints are worked out in the background after each scan, like the other checks; the groups
are worked out again when new ones come in, and kept (meta "fp_groups") for the health report.
"""

from __future__ import annotations

import json
import logging
import subprocess
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from . import procs
from .db import get_meta, session, set_meta

log = logging.getLogger("shelf.fingerprint")

SECONDS = 60          # how much of each song is fingerprinted
MIN_ITEMS = 40        # about five seconds: shorter overlaps can't tell songs apart
# The share of bits that may differ. Measured: a re-encode (even 48k AAC, or with silence added in
# front) 0.01-0.04; another mix or master of the same performance (an alternate mix, a BBC session
# remastered) 0.09-0.13; another song about 0.5. Only the same audio counts.
MAX_DISTANCE = 0.07
COMMON = 30           # a number printed by more songs than this is silence or the like
VOTES = 3             # shared numbers at the same offset before two songs are compared
KEY = "fp_groups"


def fingerprint(path: Path) -> bytes | None:
    """The first minute's fingerprint (raw little-endian 32-bit numbers), or None."""
    out = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-t", str(SECONDS), "-i", str(path), "-map", "0:a:0", "-ac", "1",
         "-f", "chromaprint", "-fp_format", "raw", "-"],
        capture_output=True, timeout=300, **procs.low_priority(),
    ).stdout
    return out if len(out) >= 4 * 8 else None


def decode(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob[: len(blob) // 4 * 4], dtype="<u4").astype(np.uint32)


def distance(a: np.ndarray, b: np.ndarray, offset: int) -> float:
    """The share of bits that differ where `b` lines up with `a` moved on by `offset` items."""
    x, y = (a, b[offset:]) if offset >= 0 else (a[-offset:], b)
    n = min(len(x), len(y))
    x, y = x[:n], y[:n]
    # Where the sound doesn't change (silence, a held note), every song prints the same: skip it.
    moving = np.ones(n, dtype=bool)
    moving[1:] = (x[1:] != x[:-1]) | (y[1:] != y[:-1])
    if moving.sum() < MIN_ITEMS:
        return 1.0
    return float(np.bitwise_count(x[moving] ^ y[moving]).sum()) / (32 * int(moving.sum()))


def _keys(fp: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """A quarter of the numbers, the same quarter in every copy (picked by value, not place), with
    their places. The lowest bits change most between encodes, so they're left out."""
    keys = fp >> 4
    pick = ((keys.astype(np.uint64) * 0x9E3779B1) & 0xFFFFFFFF) >> 30 == 0
    return keys[pick], np.nonzero(pick)[0]


def groups(fps: dict[int, np.ndarray], durations: dict[int, float]) -> list[list[int]]:
    """Songs that are the same recording, in groups of two or more (sorted)."""
    fps = {t: f for t, f in fps.items() if len(f) >= MIN_ITEMS}
    by_key: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for tid, fp in fps.items():
        keys, places = _keys(fp)
        seen: Counter = Counter()
        for k, p in zip(keys.tolist(), places.tolist()):
            seen[k] += 1
            if seen[k] <= 2:  # a number a song prints over and over is a held sound, not a fingerprint
                by_key[k].append((tid, p))
    votes: Counter = Counter()
    for entries in by_key.values():
        if len(entries) < 2 or len({t for t, _ in entries}) > COMMON:
            continue
        for i, (ta, pa) in enumerate(entries):
            for tb, pb in entries[i + 1:]:
                if ta != tb:
                    votes[(ta, tb, pb - pa) if ta < tb else (tb, ta, pa - pb)] += 1
    best: dict[tuple[int, int], tuple[int, int]] = {}
    for (ta, tb, off), n in votes.items():
        if n >= VOTES and n > best.get((ta, tb), (0, 0))[0]:
            best[(ta, tb)] = (n, off)

    parent = {t: t for t in fps}

    def root(t):
        while parent[t] != t:
            parent[t] = parent[parent[t]]
            t = parent[t]
        return t

    for (ta, tb), (_, off) in best.items():
        da, db = durations.get(ta) or 0, durations.get(tb) or 0
        if abs(da - db) > max(5.0, 0.03 * max(da, db)):
            continue
        if min(distance(fps[ta], fps[tb], o) for o in (off - 1, off, off + 1)) <= MAX_DISTANCE:
            parent[root(ta)] = root(tb)
    out: dict[int, list[int]] = defaultdict(list)
    for t in fps:
        out[root(t)].append(t)
    return sorted(sorted(g) for g in out.values() if len(g) > 1)


def refresh_groups(conn) -> list[list[int]]:
    fps, durations = {}, {}
    for r in conn.execute("SELECT id, duration, fp FROM tracks WHERE fp IS NOT NULL"):
        fps[r["id"]] = decode(r["fp"])
        durations[r["id"]] = r["duration"] or 0
    found = groups(fps, durations)
    set_meta(conn, KEY, json.dumps(found))
    return found


def stored_groups(conn) -> list[list[int]]:
    try:
        return json.loads(get_meta(conn, KEY) or "[]")
    except ValueError:
        return []


def check_pending(db_path: Path, stop=None, workers: int = 2) -> int:
    """Fingerprints songs not done yet (or changed since), then works out the groups again.
    Returns how many were done."""
    with session(db_path) as conn:
        rows = conn.execute("SELECT id, path FROM tracks WHERE fp_checked = 0 ORDER BY id").fetchall()
        missing = get_meta(conn, KEY) is None
    if rows:
        log.info("Fingerprinting %d songs", len(rows))

    def one(r):
        try:
            return fingerprint(Path(r["path"]))
        except (subprocess.SubprocessError, OSError):
            return None

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(one, r): r["id"] for r in rows}
        for fut in futures:
            if stop is not None and stop.is_set():
                pool.shutdown(wait=False, cancel_futures=True)
                break
            blob = fut.result()
            with session(db_path) as conn:
                conn.execute("UPDATE tracks SET fp = ?, fp_checked = 1 WHERE id = ?", (blob, futures[fut]))
            done += 1
    if done or missing:
        with session(db_path) as conn:
            refresh_groups(conn)
    return done
