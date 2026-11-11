"""Backups of the database: the part of Shelf a rescan can't rebuild (accounts, likes, playlists,
play history, settings).

Once a day a copy is made with SQLite's online backup, so it's whole even while Shelf is busy,
and gzipped into the backups folder: the data folder's backups/ unless the admin picked another
(another drive is safer). One a day is kept for the last week and one a week for the eight weeks
before; the newest is never thrown away.

Restoring copies a backup back over the live database, after first backing up what's there now,
so a restore picked by mistake can be undone the same way.
"""

from __future__ import annotations

import gzip
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

log = logging.getLogger("shelf.backups")
DAY = 86400
EVERY = 3600  # how often to look whether one is due
RESTORE = "-before-restore.db.gz"
SAFETY_DAYS = 30
NAME = re.compile(r"^shelf-\d{4}-\d{2}-\d{2}-\d{6}(-before-restore)?\.db\.gz$")


class BackupError(Exception):
    pass


def due(times: list[float], now: float) -> bool:
    """One a day: due when there's none in the last 23 hours (so it doesn't creep later each day)."""
    return not times or now - max(times) >= DAY - 3600


def to_keep(times: list[float], now: float, days: int = 7, weeks: int = 8) -> set[float]:
    """The newest of each of the last `days` days, then the newest of each of the `weeks` weeks before."""
    keep: set[float] = set()
    if not times:
        return keep
    keep.add(max(times))
    newest_in: dict[tuple[str, int], float] = {}
    for t in times:
        age = (now - t) / DAY
        if age < days:
            slot = ("day", int(age))
        elif age < days + weeks * 7:
            slot = ("week", int((age - days) // 7))
        else:
            continue
        newest_in[slot] = max(newest_in.get(slot, t), t)
    return keep | set(newest_in.values())


class Backups:
    def __init__(self, db_path: Path, folder: Callable[[], Path]):
        self.db_path, self.folder = db_path, folder
        self._lock = threading.Lock()
        self._stop = threading.Event()

    # ---------- what's there ----------

    def _files(self) -> list[Path]:
        d = self.folder()
        return sorted((p for p in d.glob("shelf-*.db.gz") if NAME.match(p.name)), key=lambda p: p.stat().st_mtime) \
            if d.is_dir() else []

    def list(self) -> list[dict]:
        """Newest first."""
        return [{"name": p.name, "at": p.stat().st_mtime, "size": p.stat().st_size} for p in reversed(self._files())]

    # ---------- making ----------

    def make(self, now: float | None = None, suffix: str = "") -> Path:
        now = time.time() if now is None else now
        d = self.folder()
        d.mkdir(parents=True, exist_ok=True)
        out = d / f"shelf-{time.strftime('%Y-%m-%d-%H%M%S', time.localtime(now))}{suffix}.db.gz"
        with self._lock, tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "copy.db"
            src, dst = sqlite3.connect(self.db_path, timeout=30), sqlite3.connect(copy)
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
            part = out.with_name(out.name + ".part")
            with open(copy, "rb") as f, gzip.open(part, "wb", compresslevel=6) as g:
                shutil.copyfileobj(f, g)
            part.replace(out)
        os.utime(out, (now, now))
        if not suffix:
            self.prune(now)
        log.info("Backed up the database to %s", out)
        return out

    def prune(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        files = [p for p in self._files() if not p.name.endswith(RESTORE)]
        keep = to_keep([p.stat().st_mtime for p in files], now)
        gone = 0
        for p in self._files():
            old = now - p.stat().st_mtime > SAFETY_DAYS * DAY if p.name.endswith(RESTORE) else p.stat().st_mtime not in keep
            if old:
                p.unlink(missing_ok=True)
                gone += 1
        return gone

    def step(self, now: float | None = None) -> Path | None:
        now = time.time() if now is None else now
        if due([p.stat().st_mtime for p in self._files() if not p.name.endswith(RESTORE)], now):
            return self.make(now)
        return None

    # ---------- restoring ----------

    def path_of(self, name: str) -> Path:
        if not NAME.match(name):
            raise BackupError("That isn’t one of Shelf’s backups")
        p = self.folder() / name
        if not p.is_file():
            raise BackupError("That backup isn’t there any more")
        return p

    def restore(self, name: str) -> Path:
        """Put a backup back. Returns the backup made of what was there just before."""
        p = self.path_of(name)
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "restore.db"
            try:
                with gzip.open(p, "rb") as g, open(copy, "wb") as f:
                    shutil.copyfileobj(g, f)
                check = sqlite3.connect(copy)
                try:
                    ok = check.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                    ok = ok and check.execute("SELECT 1 FROM sqlite_master WHERE name = 'users'").fetchone() is not None
                finally:
                    check.close()
            except (OSError, EOFError, sqlite3.DatabaseError) as e:
                raise BackupError("That backup can’t be read") from e
            if not ok:
                raise BackupError("That backup is damaged")
            safety = self.make(suffix="-before-restore")  # outside the daily rotation: kept a month
            with self._lock:
                src, dst = sqlite3.connect(copy), sqlite3.connect(self.db_path, timeout=30)
                try:
                    src.backup(dst)
                finally:
                    dst.close()
                    src.close()
        from .db import init_db
        init_db(self.db_path)  # an older backup gets the columns added since
        log.warning("Restored the database from %s (what was there is in %s)", name, safety.name)
        return safety

    # ---------- the daily loop ----------

    def start(self) -> None:
        threading.Thread(target=self._loop, name="shelf-backups", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(60 if not self._files() else EVERY):
            try:
                self.step()
            except Exception:  # try again next time
                log.exception("Backing up the database failed")
