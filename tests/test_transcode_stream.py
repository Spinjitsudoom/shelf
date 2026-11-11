import asyncio
import struct
import subprocess

from shelf import transcode


def _flac(path, seconds=60):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", str(path)], check=True)


def test_first_bytes_arrive_before_conversion_ends(tmp_path):
    src = tmp_path / "song.flac"
    _flac(src)
    cache = tmp_path / "cache"
    cache.mkdir()
    target = transcode._target(cache, src, src.stat().st_mtime, 96)

    async def run():
        gen = transcode.stream_transcode(cache, src, src.stat().st_mtime, 96, 100)
        first = await gen.__anext__()
        assert first and not target.exists()  # sent before the whole song is converted
        rest = b"".join([c async for c in gen])
        return first + rest

    data = asyncio.run(run())
    assert data[4:8] == b"ftyp"  # an MP4
    assert target.exists() and target.read_bytes() == data  # and kept for next time



def _boxes(data):
    """The top-level MP4 boxes as (type, size)."""
    out, i = [], 0
    while i < len(data):
        size, kind = struct.unpack(">I4s", data[i:i + 8])
        out.append((kind.decode(), size))
        if size < 8:  # 0 means "to the end"; a player reading a stream can't know where that is
            break
        i += size
    return out


def test_streamed_copy_has_sized_boxes(tmp_path):
    """Android's player can't read a box of unknown size from a stream ("Atom size less than header
    length"): ffmpeg wrote the whole song as one moof of size 0 when sent through a pipe."""
    src = tmp_path / "song.flac"
    _flac(src, seconds=30)
    cache = tmp_path / "cache"
    cache.mkdir()

    async def run():
        return b"".join([c async for c in transcode.stream_transcode(cache, src, src.stat().st_mtime, 96, 100)])

    boxes = _boxes(asyncio.run(run()))
    assert all(size >= 8 for _, size in boxes), boxes[:6]
    assert sum(kind == "moof" for kind, _ in boxes) > 5  # small pieces, so playback starts at once

def test_failed_transcode_leaves_no_cache(tmp_path):
    src = tmp_path / "broken.flac"
    src.write_bytes(b"fLaC" + b"\x00" * 5000)
    cache = tmp_path / "cache"
    cache.mkdir()

    async def run():
        return b"".join([c async for c in transcode.stream_transcode(cache, src, src.stat().st_mtime, 96, 100)])

    try:
        asyncio.run(run())
        raise AssertionError("should fail")
    except RuntimeError:
        pass
    assert list(cache.iterdir()) == []


def test_second_request_serves_cached_file(client):
    assert client.post("/api/login", json={"password": "hunter2"}).status_code == 200
    album = client.get("/api/albums").json()[0]
    track = client.get(f"/api/albums/{album['id']}").json()["tracks"][0]["id"]
    first = client.get(f"/api/tracks/{track}/stream?q=low")
    assert first.status_code == 200 and first.content[4:8] == b"ftyp"
    again = client.get(f"/api/tracks/{track}/stream?q=low", headers={"Range": "bytes=0-99"})
    assert again.status_code == 206 and len(again.content) == 100


def test_copies_made_before_the_fix_are_not_reused(tmp_path):
    """Copies kept before the fragment fix hold the unreadable stream; they're made again."""
    import hashlib

    src = tmp_path / "song.flac"
    _flac(src, seconds=1)
    cache = tmp_path / "cache"
    cache.mkdir()
    mtime = src.stat().st_mtime
    old = cache / (hashlib.sha1(f"{src}|{mtime}|96".encode()).hexdigest()[:24] + ".m4a")
    old.write_bytes(b"old copy")
    assert transcode.cached(cache, src, mtime, 96) is None
