"""On-demand AAC transcodes for data-saving playback and formats browsers can't play.

Each track is transcoded whole to a cached .m4a, then served like any file so the
browser can seek with Range requests. A per-file lock stops duplicate ffmpeg runs.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import struct
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


def _moov_end(head) -> int | None:
    """Where the MP4's header (its moov box) ends, once that much has arrived; None until then."""
    i = 0
    while i + 8 <= len(head):
        size, kind = struct.unpack(">I4s", head[i:i + 8])
        if size < 8:
            return None
        if kind == b"moov":
            return i + size if i + size <= len(head) else None
        i += size
    return None


def set_duration(head: bytearray, seconds: float | None) -> bool:
    """Write the song's length into an MP4 header whose length says 0, in place (the same bytes
    long, so a copy cached part way still lines up). ffmpeg can't know it while it streams, and a
    player that's told neither the length nor the size shows 0:00, and treats the song as a live
    broadcast: after a moment without signal it can't carry on where it was. True if changed."""
    end = _moov_end(head)
    if end is None or not seconds or seconds <= 0:
        return False
    changed = False

    def put(at: int, wide: bool, value: int) -> None:
        nonlocal changed
        fmt = ">Q" if wide else ">I"
        value = min(value, (1 << (64 if wide else 32)) - 2)
        if struct.unpack(fmt, head[at:at + (8 if wide else 4)])[0] == 0:
            struct.pack_into(fmt, head, at, value)
            changed = True

    def walk(i: int, stop: int, movie_scale: int) -> int:
        while i + 8 <= stop:
            size, kind = struct.unpack(">I4s", head[i:i + 8])
            if size < 8:
                break
            wide = head[i + 8] == 1
            if kind in (b"moov", b"trak", b"mdia"):
                movie_scale = walk(i + 8, i + size, movie_scale)
            elif kind in (b"mvhd", b"mdhd"):  # version, flags, two times, then timescale and duration
                at = i + (28 if wide else 20)
                scale = struct.unpack(">I", head[at:at + 4])[0]
                if scale:
                    put(at + 4, wide, round(seconds * scale))
                    if kind == b"mvhd":
                        movie_scale = scale
            elif kind == b"tkhd" and movie_scale:  # its duration is in the movie's timescale
                put(i + (36 if wide else 28), wide, round(seconds * movie_scale))
            i += size
        return movie_scale

    walk(0, end, 0)
    return changed


async def stream_transcode(cache_dir: Path, src: Path, mtime: float, kbps: int, cache_limit_mb: int,
                           duration: float | None = None):
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
    head: bytearray | None = bytearray()  # held back until the header is whole, to put the length in
    try:
        while chunk := await proc.stdout.read(64 * 1024):
            if head is not None:
                head += chunk
                if _moov_end(head) is None and len(head) < 1024 * 1024:
                    continue
                set_duration(head, duration)
                chunk, head = bytes(head), None
            if out:
                out.write(chunk)
            yield chunk
        if head:  # ended before a whole header: send what there is
            if out:
                out.write(head)
            yield bytes(head)
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


def cached(cache_dir: Path, src: Path, mtime: float, kbps: int, duration: float | None = None) -> Path | None:
    """The finished conversion of a song, if there is one (given its length, if it was kept
    without it)."""
    target = _target(cache_dir, src, mtime, kbps)
    if target.exists():
        if duration:
            _fix_length(target, duration)
        target.touch()
        return target
    return None


def _fix_length(path: Path, duration: float) -> None:
    try:
        with open(path, "r+b") as f:
            head = bytearray(f.read(64 * 1024))
            if set_duration(head, duration):
                f.seek(0)
                f.write(head[:_moov_end(head)])
    except OSError:
        pass


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
