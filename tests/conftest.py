import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from shelf.app import create_app
from shelf.config import Config


def make_track(path: Path, *, title, artist, album, track, album_artist=None, fmt="mp3", cover: Path | None = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2"]
    if cover:
        cmd += ["-i", str(cover), "-map", "0:a", "-map", "1:v", "-c:v", "mjpeg", "-disposition:v", "attached_pic"]
    meta = {"title": title, "artist": artist, "album": album, "track": str(track), "date": "2001"}
    if album_artist:
        meta["album_artist"] = album_artist
    for k, v in meta.items():
        cmd += ["-metadata", f"{k}={v}"]
    if fmt == "mp3":
        cmd += ["-c:a", "libmp3lame", "-id3v2_version", "3"]
    cmd.append(str(path))
    subprocess.run(cmd, check=True)


@pytest.fixture(scope="session")
def cover_jpg(tmp_path_factory):
    p = tmp_path_factory.mktemp("img") / "cover.jpg"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0xc02020:s=300x300",
                    "-frames:v", "1", str(p)], check=True)
    return p


@pytest.fixture()
def library(tmp_path, cover_jpg):
    root = tmp_path / "music"
    make_track(root / "Band" / "2001 - First" / "01 Opening.mp3", title="Opening", artist="Band",
               album="First", track=1, cover=cover_jpg)
    make_track(root / "Band" / "2001 - First" / "02 Closer.mp3", title="Closer", artist="Band",
               album="First", track=2, cover=cover_jpg)
    make_track(root / "band" / "Second" / "CD2" / "01 Late.flac", title="Late", artist="band",
               album="Second", track=1, fmt="flac")
    make_track(root / "band" / "Second" / " Disc 1" / "01 Early.flac", title="Early", artist="band",
               album="Second", track=1, fmt="flac")
    return root


@pytest.fixture()
def client(tmp_path, library):
    cfg = Config(music_dirs=[library], data_dir=tmp_path / "data", password="hunter2", online_lyrics=False, music_videos=False, artist_info=False, analyze_tempo=False)
    app = create_app(cfg, start_scanner=False)
    app.state.scanner.run_once()
    with TestClient(app) as c:
        yield c
