"""Adding music from the browser: songs (or ZIP files of them) are filed into a music folder as
Artist/Album/, from their own tags, the way the scanner likes it.

Cover images sent along with an album (cover.jpg, folder.png...) go into the same folder as
its songs. A file that's already there with the same size counts as a duplicate and is skipped;
a different file with the same name gets a number added. Nothing is ever overwritten.
"""

from __future__ import annotations

import re
import shutil
import tempfile
import threading
import time
import zipfile
from pathlib import Path

from .tags import AUDIO_EXTS, read_tags

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_BYTES = 4 * 1024**3
_BAD = re.compile(r'[\x00-\x1f<>:"/\\|?*]')

# Where each upload group's (a folder or ZIP the person picked) songs went, for its cover art.
_groups: dict[str, tuple[float, Path]] = {}
_lock = threading.Lock()


def safe_part(name: str | None, fallback: str) -> str:
    """A name usable as one folder or file name on any disk."""
    s = _BAD.sub(" ", (name or "").strip())
    s = re.sub(r"\s+", " ", s).strip(" .")
    return (s[:120].rstrip(" .") or fallback)


def allowed(name: str) -> bool:
    ext = Path(name).suffix.lower()
    return ext in AUDIO_EXTS or ext in IMAGE_EXTS or ext == ".zip"


def _free_name(target: Path, size: int) -> Path | None:
    """`target`, or a numbered variant if a different file has its name. None if the same
    file (same size) is already there."""
    if not target.exists():
        return target
    if target.stat().st_size == size:
        return None
    for n in range(2, 1000):
        alt = target.with_name(f"{target.stem} ({n}){target.suffix}")
        if not alt.exists():
            return alt
        if alt.stat().st_size == size:
            return None
    raise OSError("Too many files with this name")


def _remember(group: str, folder: Path) -> None:
    now = time.time()
    with _lock:
        _groups[group] = (now, folder)
        for k in [k for k, (t, _) in _groups.items() if now - t > 6 * 3600]:
            del _groups[k]


def _recall(group: str) -> Path | None:
    with _lock:
        hit = _groups.get(group)
    return hit[1] if hit else None


def place_audio(staged: Path, name: str, root: Path, group: str) -> dict:
    info = read_tags(staged)
    if info is None:
        staged.unlink(missing_ok=True)
        return {"status": "skipped", "reason": "Not a song Shelf can read"}
    artist = safe_part(info.album_artist or info.artist, "Unknown Artist")
    album = safe_part(info.album, "Unknown Album")
    folder = root / artist / album
    folder.mkdir(parents=True, exist_ok=True)
    target = _free_name(folder / safe_part(name, "song" + staged.suffix), staged.stat().st_size)
    _remember(group, folder)
    if target is None:
        staged.unlink(missing_ok=True)
        return {"status": "duplicate", "artist": artist, "album": album}
    shutil.move(str(staged), target)
    return {"status": "added", "artist": artist, "album": album, "path": str(target)}


def place_image(staged: Path, name: str, root: Path, group: str) -> dict:
    folder = _recall(group) or (root / "Uploads" / safe_part(group, "Pictures"))
    folder.mkdir(parents=True, exist_ok=True)
    target = _free_name(folder / safe_part(name, "cover" + staged.suffix), staged.stat().st_size)
    if target is None:
        staged.unlink(missing_ok=True)
        return {"status": "duplicate"}
    shutil.move(str(staged), target)
    return {"status": "added", "path": str(target)}


def place_zip(staged: Path, root: Path, group: str) -> dict:
    """Every song in a ZIP (images after them, so they find their album's folder)."""
    added = dupes = skipped = 0
    albums: set[str] = set()
    with tempfile.TemporaryDirectory(dir=staged.parent) as tmp, zipfile.ZipFile(staged) as z:
        members = [m for m in z.infolist() if not m.is_dir() and allowed(m.filename) and not m.filename.lower().endswith(".zip")]
        members.sort(key=lambda m: Path(m.filename).suffix.lower() in IMAGE_EXTS)
        for i, m in enumerate(members):
            inner = Path(m.filename)
            out = Path(tmp) / f"{i}{inner.suffix.lower()}"
            with z.open(m) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)
            sub = f"{group}/{inner.parent}"
            if inner.suffix.lower() in IMAGE_EXTS:
                r = place_image(out, inner.name, root, sub)
            else:
                r = place_audio(out, inner.name, root, sub)
                if r.get("album"):
                    albums.add(f"{r['artist']} – {r['album']}")
            added += r["status"] == "added"
            dupes += r["status"] == "duplicate"
            skipped += r["status"] == "skipped"
    staged.unlink(missing_ok=True)
    return {"status": "added" if added else "duplicate" if dupes else "skipped",
            "added": added, "duplicates": dupes, "skipped": skipped, "albums": sorted(albums)}


def place(staged: Path, name: str, root: Path, group: str) -> dict:
    ext = Path(name).suffix.lower()
    if ext == ".zip":
        return place_zip(staged, root, group)
    if ext in IMAGE_EXTS:
        return place_image(staged, name, root, group)
    return place_audio(staged, name, root, group)
