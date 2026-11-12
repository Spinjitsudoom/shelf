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
    # "v2": copies kept before 0.7.5 may hold a fragment of unknown size, which Android can't play.
    digest = hashlib.sha1(f"v2|{src}|{mtime}|{kbps}".encode()).hexdigest()[:24]
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


async def stream_transcode(cache_dir: Path, src: Path, mtime: float, kbps: int, cache_limit_mb: int):
    """Convert a song while sending it: yields the MP4 as ffmpeg writes it, so playback starts
    within a moment instead of after the whole song is converted. The bytes are kept too, and
    become the cached copy (served with seeking from then on) only if the conversion finishes.
    A fragmented MP4 is used because a normal one needs the whole song before its first byte.
    If the same song is already being converted for someone else, this one isn't kept."""
    target = _target(cache_dir, src, mtime, kbps)
    lock = _locks.setdefault(target.name, asyncio.Lock())
    keep = not lock.locked()
    if keep:
        await lock.acquire()
    tmp = target.with_suffix(f".{id(lock)}.part") if keep else None
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src),
        "-map", "0:a:0", "-vn", "-c:a", "aac", "-b:a", f"{kbps}k",
        # Every audio frame is a keyframe, so without a fragment length ffmpeg 9 writes the whole
        # song as one fragment whose size (unknown in a pipe) is left as 0, which Android can't read.
        "-movflags", "+frag_keyframe+empty_moov+default_base_moof", "-frag_duration", "2000000",
        "-f", "mp4", "pipe:1",
        # Its complaints are let go (see live()): unread, they could stall the song.
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, **procs.no_window(),
    )
    out = open(tmp, "wb") if tmp else None
    ok = False
    try:
        while chunk := await proc.stdout.read(64 * 1024):
            if out:
                out.write(chunk)
            yield chunk
        await proc.wait()
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg couldn’t convert {src} (exit {proc.returncode})")
        ok = True
    finally:
        if proc.returncode is None:  # the listener went away mid-song
            proc.kill()
            await proc.wait()
        if out:
            out.close()
            if ok:
                tmp.replace(target)
            else:
                tmp.unlink(missing_ok=True)
        if keep:
            lock.release()
            _locks.pop(target.name, None)
    if ok and keep:
        _prune(cache_dir, cache_limit_mb)


def cached(cache_dir: Path, src: Path, mtime: float, kbps: int) -> Path | None:
    """The finished conversion of a song, if there is one."""
    target = _target(cache_dir, src, mtime, kbps)
    if target.exists():
        target.touch()
        return target
    return None


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


# ---------- live conversions (Subsonic apps: other formats, and starting part way in) ----------

# codec: (ffmpeg encoder, container, mime type, default kbps)
LIVE = {
    "aac": ("aac", "adts", "audio/aac", 192),
    "mp3": ("libmp3lame", "mp3", "audio/mpeg", 192),
    "opus": ("libopus", "ogg", "audio/ogg", 128),
    "flac": ("flac", "flac", "audio/flac", 0),
}
ALIASES = {"m4a": "aac", "mp4": "aac", "adts": "aac", "ogg": "opus", "oga": "opus"}


def live_codec(fmt: str | None) -> str | None:
    """The codec a format name asks for ("mp3", "opus", "m4a"...), or None if Shelf can't make it."""
    f = (fmt or "").lower().strip()
    f = ALIASES.get(f, f)
    return f if f in LIVE else None


async def live(src: Path, codec: str, kbps: int, offset: float = 0.0):
    """Convert a song while sending it, from `offset` seconds in, nothing kept: for formats other
    than the cached AAC copies, and for seeking in a conversion (OpenSubsonic transcodeOffset)."""
    encoder, container, _, default = LIVE[codec]
    args = ["ffmpeg", "-nostdin", "-v", "error"]
    if offset > 0:
        args += ["-ss", f"{offset:.3f}"]
    args += ["-i", str(src), "-map", "0:a:0", "-vn", "-c:a", encoder]
    if codec != "flac":
        args += ["-b:a", f"{kbps or default}k"]
    if codec == "opus":
        args += ["-ar", "48000"]
    args += ["-f", container, "pipe:1"]
    # ffmpeg's complaints are let go: a damaged file can say more than a pipe holds while nobody
    # reads it, which would stall the song. No sound at all says it failed.
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                                                **procs.no_window())
    try:
        got = False
        while chunk := await proc.stdout.read(64 * 1024):
            got = True
            yield chunk
        await proc.wait()
        if proc.returncode != 0 and not got:
            raise RuntimeError(f"ffmpeg couldn’t convert {src}")
    finally:
        if proc.returncode is None:  # the listener went away
            proc.kill()
            await proc.wait()
