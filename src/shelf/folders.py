"""Music folders, managed from Settings.

The list starts as config.toml's `music_dirs`; once it's changed in Settings it's kept in
the database and wins over config.toml (SHELF_MUSIC_DIRS, when set, wins over both, and
the list can't be changed in the app). Picking a folder means browsing the server's disks,
so the browser lists folders only, never files.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .db import get_meta, session, set_meta

KEY = "music_dirs"
ENV = "SHELF_MUSIC_DIRS"


def locked() -> bool:
    """True when the folders come from the environment and can't be changed here."""
    return bool(os.environ.get(ENV))


def load_saved(db_path: Path) -> list[Path] | None:
    with session(db_path) as conn:
        raw = get_meta(conn, KEY)
    if not raw:
        return None
    try:
        return [Path(p) for p in json.loads(raw)]
    except (ValueError, TypeError):
        return None


def save(db_path: Path, dirs: list[Path]) -> None:
    with session(db_path) as conn:
        set_meta(conn, KEY, json.dumps([str(d) for d in dirs]))


def _inside(a: Path, b: Path) -> bool:
    """Is `a` the same as or inside `b`?"""
    try:
        a.relative_to(b)
        return True
    except ValueError:
        return False


def check_new(path: str, existing: list[Path], data_dir: Path, replacing: Path | None = None) -> Path:
    """A folder to add, made absolute; raises ValueError with a readable reason if it can't be."""
    p = Path(path).expanduser()
    if not p.is_absolute():
        raise ValueError("Choose a folder by its full path, starting with /")
    p = p.resolve()
    if not p.is_dir():
        raise ValueError(f"{p} isn’t a folder Shelf can see")
    if not os.access(p, os.R_OK | os.X_OK):
        raise ValueError(f"Shelf isn’t allowed to read {p}")
    if _inside(data_dir.resolve(), p) or _inside(p, data_dir.resolve()):
        raise ValueError("That folder holds Shelf’s own data; choose the folder with your music")
    for d in existing:
        if replacing is not None and d == replacing:
            continue
        d = d.resolve() if d.exists() else d
        if p == d:
            raise ValueError(f"{p} is already in your library")
        if _inside(p, d):
            raise ValueError(f"{p} is inside {d}, which is already in your library")
        if _inside(d, p):
            raise ValueError(f"{d} is already in your library and is inside {p}; remove it first, then add {p}")
    return p


def counts(db_path: Path, dirs: list[Path]) -> list[dict]:
    with session(db_path) as conn:
        out = []
        for d in dirs:
            prefix = str(d).rstrip("/\\") + os.sep
            n = conn.execute("SELECT COUNT(*) FROM tracks WHERE substr(path, 1, ?) = ?", (len(prefix), prefix)).fetchone()[0]
            out.append({"path": str(d), "available": d.is_dir(), "tracks": n})
    return out


def remap(db_path: Path, old: Path, new: Path) -> int:
    """After a folder moves: point songs at their new place when the same file is there,
    so likes, playlists and history stay with them. Returns how many were found."""
    old_prefix = str(old).rstrip("/\\") + os.sep
    moved = 0
    with session(db_path) as conn:
        rows = conn.execute("SELECT id, path FROM tracks WHERE substr(path, 1, ?) = ?",
                            (len(old_prefix), old_prefix)).fetchall()
        for r in rows:
            target = new / r["path"][len(old_prefix):]
            if target.is_file() and not conn.execute("SELECT 1 FROM tracks WHERE path = ?", (str(target),)).fetchone():
                conn.execute("UPDATE tracks SET path = ? WHERE id = ?", (str(target), r["id"]))
                moved += 1
    return moved


def browse(path: str | None, music_dirs: list[Path]) -> dict:
    """The folders inside `path` (no files), and some places to start from."""
    home = Path.home()
    starts = []
    if os.name == "nt":  # the Music folder, then each drive
        places = [home, home / "Music", *(Path(f"{d}:\\") for d in "CDEFGHIJKLMNOPQRSTUVWXYZ")]
    else:
        places = [home, Path("/mnt"), Path("/media"), Path("/var/mnt"), Path(f"/run/media/{home.name}"), Path("/")]
    for p in places:
        if p.is_dir() and str(p) not in {s["path"] for s in starts}:
            starts.append({"name": "Home" if p == home else str(p), "path": str(p)})
    here = Path(path).expanduser() if path else home
    if not here.is_absolute():
        here = home
    here = here.resolve()
    dirs, error = [], None
    try:
        with os.scandir(here) as it:
            for e in it:
                if e.name.startswith("."):
                    continue
                try:
                    if e.is_dir():
                        dirs.append({"name": e.name, "path": str(here / e.name)})
                except OSError:
                    continue
    except PermissionError:
        error = "Shelf isn’t allowed to look inside this folder"
    except OSError as e:
        error = f"Couldn’t open this folder ({e.strerror or e})"
    dirs.sort(key=lambda d: d["name"].casefold())
    return {
        "path": str(here),
        "parent": str(here.parent) if here.parent != here else None,
        "dirs": dirs[:1000],
        "error": error,
        "starts": starts,
        "inLibrary": any(_inside(here, d) for d in music_dirs),
    }
