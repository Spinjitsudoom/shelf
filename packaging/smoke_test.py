"""Checks a built Shelf server really works: starts it on a fresh folder with one song,
signs in, waits for the scan, and streams the song both as-is and converted (ffmpeg).

    python packaging/smoke_test.py <command that starts the server...>
e.g. python packaging/smoke_test.py "dist/Shelf Server/shelf-server.exe"
     python packaging/smoke_test.py uv run shelf

Needs ffmpeg on PATH (to make the test song). Exits non-zero, saying why, if anything fails.
"""

from __future__ import annotations

import http.cookiejar
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

PASSWORD = "smoke-test-pass"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> None:
    cmd = sys.argv[1:]
    if not cmd:
        sys.exit(__doc__)
    tmp = Path(tempfile.mkdtemp(prefix="shelf-smoke-"))
    music = tmp / "music" / "Test Artist" / "Test Album"
    music.mkdir(parents=True)
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
                    "-metadata", "title=Smoke Song", "-metadata", "artist=Test Artist",
                    "-metadata", "album=Test Album", "-metadata", "track=1", str(music / "01 Smoke Song.flac")],
                   check=True)
    port = free_port()
    config = tmp / "config.toml"
    config.write_text(
        f"music_dirs = ['{tmp / 'music'}']\n"
        f"data_dir = '{tmp / 'data'}'\n"
        f"password = '{PASSWORD}'\nhost = '127.0.0.1'\nport = {port}\n"
        "online_lyrics = false\nmusic_videos = false\nartist_info = false\n",
        encoding="utf-8",
    )
    base = f"http://127.0.0.1:{port}"
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def call(path: str, body: dict | None = None, raw: bool = False):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"} if body is not None else {})
        with opener.open(req, timeout=60) as r:
            data = r.read()
            return data if raw else json.loads(data)

    log = open(tmp / "server.log", "wb")
    proc = subprocess.Popen(cmd, env={**os.environ, "SHELF_CONFIG": str(config)}, stdout=log, stderr=subprocess.STDOUT)
    ok = False
    try:
        for _ in range(120):
            if proc.poll() is not None:
                raise SystemExit(f"The server stopped (exit {proc.returncode})")
            try:
                if call("/api/ping").get("app") == "shelf":
                    break
            except OSError:
                time.sleep(0.5)
        else:
            raise SystemExit("The server didn't answer within a minute")
        print("server answers")
        call("/api/login", {"username": "admin", "password": PASSWORD})
        print("signed in")
        for _ in range(120):
            if call("/api/library")["tracks"] == 1 and not call("/api/library")["scan"].get("running"):
                break
            time.sleep(0.5)
        else:
            raise SystemExit("The scan didn't find the test song")
        albums = call("/api/albums")
        tracks = call(f"/api/albums/{albums[0]['id']}")["tracks"]
        assert tracks[0]["title"] == "Smoke Song", tracks
        print("scanned:", tracks[0]["artist"], "-", tracks[0]["title"])
        original = call(f"/api/tracks/{tracks[0]['id']}/stream", raw=True)
        assert original[:4] == b"fLaC", original[:16]
        converted = call(f"/api/tracks/{tracks[0]['id']}/stream?q=low", raw=True)
        assert converted[4:8] == b"ftyp", converted[:16]  # an MP4 (AAC) file
        print(f"streams: original {len(original)} bytes, converted {len(converted)} bytes")
        call("/", raw=True)  # the web app itself
        print("web app served")
        ok = True
    finally:
        proc.terminate()
        try:
            proc.wait(15)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
        if not ok:
            print("---- server log ----")
            print((tmp / "server.log").read_text(errors="replace")[-4000:])
    print("Smoke test passed")


if __name__ == "__main__":
    main()
