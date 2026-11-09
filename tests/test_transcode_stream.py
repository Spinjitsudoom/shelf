import asyncio
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
