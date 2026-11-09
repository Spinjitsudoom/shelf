"""Ripping CDs: put a disc in the server's drive and it goes onto the shelf.

1. Read the disc's table of contents (cd-paranoia) and work out its MusicBrainz disc ID.
2. Look the disc up on MusicBrainz for the artist, album, year and track titles (by disc ID,
   then by its track layout), and fetch the cover from the Cover Art Archive. Unknown discs
   get placeholders to fill in.
3. Rip each track with cd-paranoia (which re-reads scratched spots until it gets them right),
   encode it to FLAC (lossless) with its tags and cover, and file it as
   <music folder>/<Artist>/<Album>/<NN Title>.flac with cover.jpg beside it.
4. Eject the disc and rescan.

Everything happens on a background thread; `state` says how it's going.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import __version__
from .uploads import safe_part

log = logging.getLogger("shelf.ripper")
DEVICE = os.environ.get("SHELF_CD_DEVICE", "/dev/sr0")
PARANOIA = os.environ.get("SHELF_CD_PARANOIA", "cd-paranoia")
AGENT = f"Shelf/{__version__} (self-hosted music server)"
_TRACK = re.compile(r"^\s*(\d+)\.\s+(\d+)\s+\[[^\]]+\]\s+(\d+)\s+\[")


def parse_toc(text: str) -> list[dict]:
    """cd-paranoia -Q's table: [{number, start, length}] in sectors (start without the 2 s lead-in)."""
    out = []
    for line in text.splitlines():
        m = _TRACK.match(line)
        if m:
            out.append({"number": int(m.group(1)), "length": int(m.group(2)), "start": int(m.group(3))})
    return out


def toc_offsets(tracks: list[dict]) -> tuple[int, int, int, list[int]]:
    """(first, last, lead-out, offsets) as MusicBrainz counts them (with the 150-sector lead-in)."""
    first, last = tracks[0]["number"], tracks[-1]["number"]
    offsets = [t["start"] + 150 for t in tracks]
    leadout = tracks[-1]["start"] + tracks[-1]["length"] + 150
    return first, last, leadout, offsets


def disc_id(first: int, last: int, leadout: int, offsets: list[int]) -> str:
    """The MusicBrainz disc ID (as libdiscid computes it)."""
    s = f"{first:02X}{last:02X}{leadout:08X}"
    padded = [0] * 99
    for i, o in enumerate(offsets):
        padded[first - 1 + i] = o
    s += "".join(f"{o:08X}" for o in padded)
    digest = hashlib.sha1(s.encode("ascii")).digest()
    return base64.b64encode(digest).decode().translate(str.maketrans("+/=", "._-"))


def _get(url: str, timeout: float = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def lookup(did: str, first: int, last: int, leadout: int, offsets: list[int]) -> dict | None:
    """What MusicBrainz knows about a disc: {artist, album, year, tracks[], releaseId, groupId}."""
    toc = "+".join(str(x) for x in [first, last, leadout, *offsets])
    inc = "recordings+artist-credits+release-groups"
    for url in (f"https://musicbrainz.org/ws/2/discid/{did}?inc={inc}&fmt=json",
                f"https://musicbrainz.org/ws/2/discid/-?toc={toc}&inc={inc}&fmt=json"):
        try:
            data = json.loads(_get(url))
        except (urllib.error.URLError, OSError, ValueError):
            continue
        for rel in data.get("releases", []):
            for medium in rel.get("media", []):
                if len(medium.get("tracks", [])) != last - first + 1:
                    continue
                credit = lambda ac: "".join(a.get("name", "") + a.get("joinphrase", "") for a in ac or [])
                album_artist = credit(rel.get("artist-credit")) or "Unknown Artist"
                return {
                    "artist": album_artist,
                    "album": rel.get("title") or "Unknown Album",
                    "year": (rel.get("date") or "")[:4] or None,
                    "disc": medium.get("position") if len(rel.get("media", [])) > 1 else None,
                    "discs": len(rel.get("media", [])),
                    "releaseId": rel.get("id"),
                    "groupId": (rel.get("release-group") or {}).get("id"),
                    "tracks": [{"title": t.get("title") or f"Track {i + 1}",
                                "artist": credit(t.get("artist-credit")) or album_artist}
                               for i, t in enumerate(medium["tracks"])],
                }
    return None


def fetch_cover(release_id: str | None, group_id: str | None) -> bytes | None:
    for kind, mbid in (("release", release_id), ("release-group", group_id)):
        if not mbid:
            continue
        try:
            return _get(f"https://coverartarchive.org/{kind}/{mbid}/front-500", timeout=30)
        except (urllib.error.URLError, OSError):
            continue
    return None


def has_audio_disc() -> bool:
    """Whether the drive holds a disc with audio tracks, asked of udev (instant, unlike
    cd-paranoia, which can wait minutes on an empty drive). True if udev can't say."""
    try:
        out = subprocess.run(["udevadm", "info", "-q", "property", "-n", DEVICE],
                             capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return True
    if "ID_CDROM=" not in out:
        return True  # not a device udev knows (or tests): let cd-paranoia find out
    props = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    if props.get("ID_CDROM_MEDIA") != "1":
        return False
    return props.get("ID_CDROM_MEDIA_TRACK_COUNT_AUDIO", "1") != "0"


class Ripper:
    def __init__(self, on_done=None):
        self.on_done = on_done  # called after a rip, to rescan
        self.state: dict = {"status": "idle"}
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._toc: list[dict] = []
        self._cover: bytes | None = None

    @property
    def available(self) -> bool:
        return Path(DEVICE).exists() and shutil.which(PARANOIA) is not None

    def _set(self, **kw) -> None:
        with self._lock:
            self.state = {**self.state, **kw}

    def read_disc(self) -> None:
        if self.state.get("status") in ("reading", "ripping"):
            return
        self._set(status="reading", error=None, disc=None, progress=None)
        threading.Thread(target=self._read, name="shelf-cd-read", daemon=True).start()

    def _read(self) -> None:
        try:
            if not has_audio_disc():
                self._set(status="error", error="There’s no audio CD in the drive.")
                return
            out = subprocess.run([PARANOIA, "-d", DEVICE, "-Q"], capture_output=True, timeout=120, text=True)
            tracks = parse_toc(out.stderr + out.stdout)
            if not tracks:
                self._set(status="error", error="There’s no audio CD in the drive.")
                return
            self._toc = tracks
            first, last, leadout, offsets = toc_offsets(tracks)
            did = disc_id(first, last, leadout, offsets)
            info = lookup(did, first, last, leadout, offsets)
            self._cover = fetch_cover(info.get("releaseId"), info.get("groupId")) if info else None
            if not info:
                info = {"artist": "", "album": "", "year": None, "tracks": [{"title": f"Track {t['number']}", "artist": ""} for t in tracks]}
            for t, m in zip(info["tracks"], tracks):
                t["seconds"] = round(m["length"] / 75)
            self._set(status="ready", disc={**info, "discId": did, "found": bool(info.get("album")),
                                            "cover": self._cover is not None})
        except (OSError, subprocess.SubprocessError) as e:
            self._set(status="error", error=f"Couldn’t read the disc: {e}")

    def cover(self) -> bytes | None:
        return self._cover

    def rip(self, root: Path, artist: str, album: str, year: str | None, titles: list[str], disc: int | None = None) -> None:
        if self.state.get("status") != "ready" or not self._toc:
            raise ValueError("Read the disc first")
        self._cancel.clear()
        args = (root, artist, album, year, titles, disc)
        self._set(status="ripping", progress={"track": 0, "total": len(self._toc), "done": 0})
        threading.Thread(target=self._rip, args=args, name="shelf-cd-rip", daemon=True).start()

    def cancel(self) -> None:
        self._cancel.set()

    def _rip(self, root: Path, artist: str, album: str, year: str | None, titles: list[str], disc: int | None) -> None:
        artist_dir = safe_part(artist, "Unknown Artist")
        album_name = safe_part(album, "Unknown Album")
        folder = root / artist_dir / (f"{album_name} (Disc {disc})" if disc else album_name)
        try:
            folder.mkdir(parents=True, exist_ok=True)
            cover_path = None
            if self._cover:
                cover_path = folder / "cover.jpg"
                cover_path.write_bytes(self._cover)
            total = len(self._toc)
            with tempfile.TemporaryDirectory() as tmp:
                for i, t in enumerate(self._toc):
                    if self._cancel.is_set():
                        self._set(status="ready", progress=None, error="Ripping stopped. The songs done so far are kept.")
                        return
                    self._set(progress={"track": i + 1, "total": total, "done": i,
                                        "title": titles[i] if i < len(titles) else f"Track {i + 1}"})
                    wav = Path(tmp) / f"{i}.wav"
                    r = subprocess.run([PARANOIA, "-d", DEVICE, "-w", str(t["number"]), str(wav)],
                                       capture_output=True, timeout=3600)
                    if r.returncode != 0 or not wav.exists():
                        raise OSError(f"track {t['number']} couldn’t be read (the disc may be badly scratched)")
                    title = titles[i] if i < len(titles) and titles[i].strip() else f"Track {t['number']}"
                    out = folder / f"{t['number']:02d} {safe_part(title, 'Track')}.flac"
                    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(wav)]
                    if cover_path:
                        cmd += ["-i", str(cover_path), "-map", "0:a", "-map", "1:v", "-c:v", "copy",
                                "-disposition:v", "attached_pic"]
                    cmd += ["-c:a", "flac", "-compression_level", "8",
                            "-metadata", f"title={title}", "-metadata", f"artist={artist}",
                            "-metadata", f"album_artist={artist}", "-metadata", f"album={album}",
                            "-metadata", f"track={t['number']}/{total}"]
                    if year:
                        cmd += ["-metadata", f"date={year}"]
                    if disc:
                        cmd += ["-metadata", f"disc={disc}"]
                    cmd.append(str(out))
                    enc = subprocess.run(cmd, capture_output=True, timeout=600)
                    if enc.returncode != 0:
                        raise OSError(enc.stderr.decode(errors="replace")[-300:])
                    wav.unlink(missing_ok=True)
            self._set(status="done", progress={"track": total, "total": total, "done": total},
                      result={"folder": str(folder), "artist": artist, "album": album})
            subprocess.run(["eject", DEVICE], capture_output=True, timeout=30)
            if self.on_done:
                self.on_done()
        except (OSError, subprocess.SubprocessError) as e:
            log.exception("Ripping failed")
            self._set(status="error", error=f"Ripping failed: {e}")

    def eject(self) -> None:
        if self.state.get("status") == "ripping":
            return
        subprocess.run(["eject", DEVICE], capture_output=True, timeout=30)
        self._set(status="idle", disc=None, progress=None, error=None)
