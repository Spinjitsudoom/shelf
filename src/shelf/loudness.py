"""Measure track loudness (EBU R128) for volume normalization.

Tracks with ReplayGain/R128 tags get their loudness from the tags at scan time; the rest
are measured here with ffmpeg in the background, a couple at a time at low priority.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import procs
from .db import session

log = logging.getLogger("shelf.loudness")

_I = re.compile(r"I:\s+(-?[\d.]+|-inf)\s+LUFS")
_PEAK = re.compile(r"Peak:\s+(-?[\d.]+|-inf)\s+dBFS")


def measure(path: Path) -> tuple[float | None, float | None]:
    """Integrated loudness (LUFS) and sample peak (dBFS) of a file."""
    try:
        out = subprocess.run(
            ["ffmpeg", "-nostdin", "-nostats", "-hide_banner", "-i", str(path), "-map", "0:a:0",
             "-af", "ebur128=peak=sample", "-f", "null", "-"],
            capture_output=True, timeout=600, **procs.low_priority(),
        ).stderr.decode(errors="replace")
    except (subprocess.SubprocessError, OSError):
        return None, None
    summary = out[out.rfind("Summary:"):]
    i, p = _I.search(summary), _PEAK.search(summary)
    lufs = float(i.group(1)) if i and i.group(1) != "-inf" else None
    peak = float(p.group(1)) if p and p.group(1) != "-inf" else None
    return lufs, peak


def pending_count(db_path: Path) -> tuple[int, int]:
    with session(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
        todo = conn.execute("SELECT COUNT(*) FROM tracks WHERE loud_checked = 0").fetchone()[0]
    return total - todo, total


def analyze_pending(db_path: Path, stop=None, progress=None, workers: int = 2, gate=None) -> int:
    with session(db_path) as conn:
        rows = conn.execute("SELECT id, path FROM tracks WHERE loud_checked = 0 ORDER BY id").fetchall()
    if not rows:
        return 0
    log.info("Measuring loudness of %d tracks for volume normalization", len(rows))
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(procs.gated(gate, measure), Path(r["path"])): r["id"] for r in rows}
        for fut in futures:
            if stop is not None and stop.is_set():
                pool.shutdown(wait=False, cancel_futures=True)
                break
            lufs, peak = fut.result()
            with session(db_path) as conn:
                conn.execute(
                    "UPDATE tracks SET lufs = ?, peak = ?, loud_checked = 1 WHERE id = ?",
                    (lufs, peak, futures[fut]),
                )
            done += 1
            if progress:
                progress(done)
    log.info("Loudness measured for %d tracks", done)
    return done
