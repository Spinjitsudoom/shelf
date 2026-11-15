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


def _length(data):
    """The song's length (seconds) from an MP4's header: mvhd's duration over its timescale."""
    i = data.index(b"mvhd") - 4
    version = data[i + 8]
    at = i + (28 if version else 20)
    scale = struct.unpack(">I", data[at:at + 4])[0]
    dur = struct.unpack(">Q" if version else ">I", data[at + 4:at + (12 if version else 8)])[0]
    return dur / scale


def test_streamed_copy_says_how_long_the_song_is(tmp_path):
    """Sent while it's converted, ffmpeg can't know the length and writes 0: Android's player then
    shows 0:00 and treats the song as live radio, starting over after a dropped connection."""
    src = tmp_path / "song.flac"
    _flac(src, seconds=30)
    cache = tmp_path / "cache"
    cache.mkdir()

    async def run(duration):
        return b"".join([c async for c in transcode.stream_transcode(cache, src, src.stat().st_mtime, 96, 100, duration)])

    plain = asyncio.run(run(None))
    assert _length(plain) == 0
    transcode._target(cache, src, src.stat().st_mtime, 96).unlink()
    data = asyncio.run(run(30.0))
    assert abs(_length(data) - 30.0) < 0.01
    assert len(data) == len(plain)  # the same bytes long: a copy cached part way still lines up
    assert transcode._target(cache, src, src.stat().st_mtime, 96).read_bytes() == data  # kept with it


def test_copies_kept_without_a_length_get_one(tmp_path):
    src = tmp_path / "song.flac"
    _flac(src, seconds=5)
    cache = tmp_path / "cache"
    cache.mkdir()
    mtime = src.stat().st_mtime

    async def run():
        return b"".join([c async for c in transcode.stream_transcode(cache, src, mtime, 96, 100)])

    before = asyncio.run(run())
    kept = transcode.cached(cache, src, mtime, 96, 5.0)
    after = kept.read_bytes()
    assert _length(before) == 0 and abs(_length(after) - 5.0) < 0.01 and len(after) == len(before)
    assert transcode.set_duration(bytearray(after), 9.0) is False  # a length already there stays


def test_the_server_sends_the_length(client):
    assert client.post("/api/login", json={"password": "hunter2"}).status_code == 200
    album = client.get("/api/albums").json()[0]
    track = client.get(f"/api/albums/{album['id']}").json()["tracks"][0]
    sent = client.get(f"/api/tracks/{track['id']}/stream?q=low").content
    assert abs(_length(sent) - track["duration"]) < 0.01
