"""On-demand AAC transcodes for data-saving playback and formats browsers can't play.

Each track is transcoded whole to a cached .m4a, then served like any file so the
browser can seek with Range requests. A per-file lock stops duplicate ffmpeg runs.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
from . import procs

log = logging.getLogger("shelf.transcode")

# Streaming tiers (AAC kbps). "original" sends the file untouched.
QUALITIES = {"veryhigh": 320, "high": 192, "normal": 128, "low": 96}

_locks: dict[str, asyncio.Lock] = {}


def _target(cache_dir: Path, src: Path, mtime: float, kbps: int) -> Path:
    digest = hashlib.sha1(f"{src}|{mtime}|{kbps}".encode()).hexdigest()[:24]
    return cache_dir / f"{digest}.m4a"


async def transcode(cache_dir: Path, src: Path, mtime: float, kbps: int, cache_limit_mb: int) -> Path:
    target = _target(cache_dir, src, mtime, kbps)
    if target.exists():
        target.touch()  # mark as recently used for pruning
        return target
    lock = _locks.setdefault(target.name, asyncio.Lock())
    async with lock:
        if target.exists():
            return target
        tmp = target.with_suffix(".part")
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src),
            "-map", "0:a:0", "-vn", "-c:a", "aac", "-b:a", f"{kbps}k",
            "-movflags", "+faststart", "-f", "mp4", str(tmp),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE, **procs.no_window(),
        )
        _, err = await proc.communicate()
        if proc.returncode != 0:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"ffmpeg failed for {src}: {err.decode(errors='replace')[:500]}")
        tmp.replace(target)
    _locks.pop(target.name, None)
    _prune(cache_dir, cache_limit_mb)
    return target


def cache_size(cache_dir: Path) -> int:
    return sum(p.stat().st_size for p in cache_dir.glob("*.m4a"))


def clear_cache(cache_dir: Path) -> int:
    freed = 0
    for p in cache_dir.glob("*.m4a"):
        try:
            freed += p.stat().st_size
            p.unlink()
        except OSError:
            pass
    return freed


def _prune(cache_dir: Path, limit_mb: int) -> None:
    files = sorted(cache_dir.glob("*.m4a"), key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in files)
    limit = limit_mb * 1024 * 1024
    while files and total > limit:
        oldest = files.pop(0)
        total -= oldest.stat().st_size
        oldest.unlink(missing_ok=True)
