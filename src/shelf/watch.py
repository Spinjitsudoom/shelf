"""The watch folder: music dropped into it is renamed from its tags ("04 Riff Raff.flac") and
filed into the music folder as Artist/Album, the way browser uploads are (uploads.py).

Every half minute the folder is looked through. A file is only taken once it has stopped
changing (the same size and time on two looks in a row, and untouched for the settle time), so
a song still being copied in is left alone. Covers next to the songs go along with them; ZIPs
are unpacked; folders left empty are tidied away; anything else stays where it is.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Callable

from . import uploads
from .tags import AUDIO_EXTS, read_tags

log = logging.getLogger("shelf.watch")
EVERY = 30


class Watcher:
    def __init__(self, folder: Callable[[], Path | None], root: Callable[[], Path | None],
                 on_filed: Callable[[int], None] | None = None, settle: float = 30):
        self.folder, self.root, self.on_filed, self.settle = folder, root, on_filed, settle
        self._seen: dict[Path, tuple[int, float]] = {}
        self._stop = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._loop, name="shelf-watch", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(EVERY):
            try:
                self.tick()
            except Exception:  # keep watching
                log.exception("Filing from the watch folder failed")

    def tick(self, now: float | None = None) -> int:
        """Look once; file what's settled. Returns how many songs were added."""
        now = time.time() if now is None else now
        inbox, root = self.folder(), self.root()
        if not inbox or not root or not inbox.is_dir():
            return 0
        seen, ready = {}, []
        for p in inbox.rglob("*"):
            if not p.is_file() or p.name.startswith("."):
                continue
            st = p.stat()
            seen[p] = (st.st_size, st.st_mtime)
            if self._seen.get(p) == seen[p] and now - st.st_mtime >= self.settle:
                ready.append(p)
        self._seen = seen
        # Songs first (so their covers know where their album went), then ZIPs, then pictures.
        order = lambda p: (p.suffix.lower() in uploads.IMAGE_EXTS, p.suffix.lower() == ".zip", str(p))
        added = 0
        for p in sorted(ready, key=order):
            ext, group = p.suffix.lower(), f"watch:{p.parent}"
            try:
                if ext in AUDIO_EXTS:
                    info = read_tags(p)
                    name = p.name
                    if info and info.title:
                        number = f"{info.track_no:02d} " if info.track_no else ""
                        name = uploads.safe_part(f"{number}{info.title}", p.stem) + ext
                    added += uploads.place_audio(p, name, root, group)["status"] == "added"
                elif ext == ".zip":
                    added += uploads.place_zip(p, root, group).get("added", 0)
                elif ext in uploads.IMAGE_EXTS and uploads._recall(group):
                    uploads.place_image(p, p.name, root, group)
            except OSError as e:
                log.warning("Couldn’t file %s from the watch folder: %s", p.name, e)
        for d in sorted((d for d in inbox.rglob("*") if d.is_dir()), key=lambda d: -len(d.parts)):
            try:
                d.rmdir()  # only if empty
            except OSError:
                pass
        if added:
            log.info("Filed %d songs from the watch folder", added)
            if self.on_filed:
                self.on_filed(added)
        return added
