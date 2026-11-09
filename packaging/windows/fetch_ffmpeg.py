"""Download ffmpeg and ffprobe for Windows into a folder (default: dist/Shelf Server/ffmpeg).

Uses the newest stable LGPL build from github.com/BtbN/FFmpeg-Builds, and keeps its licence
next to the programs.

    python packaging/windows/fetch_ffmpeg.py [dest]
"""

from __future__ import annotations

import io
import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

RELEASE = "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/tags/latest"
ASSET = re.compile(r"^ffmpeg-n(\d+)\.(\d+)-latest-win64-lgpl-\d+\.\d+\.zip$")


def main() -> None:
    dest = Path(sys.argv[1] if len(sys.argv) > 1 else "dist/Shelf Server/ffmpeg")
    req = urllib.request.Request(RELEASE, headers={"User-Agent": "shelf-build", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        assets = json.load(r)["assets"]
    stable = [(tuple(map(int, m.groups())), a) for a in assets if (m := ASSET.match(a["name"]))]
    if not stable:
        sys.exit("No stable Windows ffmpeg build found")
    _, asset = max(stable, key=lambda x: x[0])
    print("Downloading", asset["name"])
    with urllib.request.urlopen(asset["browser_download_url"], timeout=600) as r:
        data = r.read()
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in z.namelist():
            base = name.rsplit("/", 1)[-1]
            if base in ("ffmpeg.exe", "ffprobe.exe", "LICENSE.txt"):
                (dest / ("FFMPEG-LICENSE.txt" if base == "LICENSE.txt" else base)).write_bytes(z.read(name))
    missing = [n for n in ("ffmpeg.exe", "ffprobe.exe") if not (dest / n).exists()]
    if missing:
        sys.exit(f"The download didn't contain {', '.join(missing)}")
    print("ffmpeg is in", dest)


if __name__ == "__main__":
    main()
