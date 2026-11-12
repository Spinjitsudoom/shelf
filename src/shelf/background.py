"""When the server may measure songs in the background (loudness, tempo and key, how songs
sound, duplicates): any time, only at night, or never. Measuring a big library takes a long
time and keeps a small computer (a Raspberry Pi, an old laptop) busy, so an admin can keep it to
the hours nobody's listening. Songs measured stay measured; new ones wait their turn.
"""

from __future__ import annotations

import time
from pathlib import Path

from .db import get_meta, session, set_meta

MODES = ("always", "night", "never")
NIGHT = (1, 7)  # 1 a.m. to 7 a.m., the server's own time


def mode(db_path: Path) -> str:
    with session(db_path) as conn:
        m = get_meta(conn, "background_work")
    return m if m in MODES else "always"


def set_mode(db_path: Path, value: str) -> None:
    if value not in MODES:
        raise ValueError(f"Background work is one of {', '.join(MODES)}")
    with session(db_path) as conn:
        set_meta(conn, "background_work", value)


def allowed(m: str, hour: int) -> bool:
    if m == "never":
        return False
    if m == "night":
        return NIGHT[0] <= hour < NIGHT[1]
    return True


class Turn:
    """The `stop` a measuring run checks between songs: it ends the run when the server is
    stopping, a scan is wanted (new music shouldn't wait behind days of measuring), its time
    is up (so the regular rescan happens) or the allowed hours are over. What's left is measured
    on the next run, once it may."""

    def __init__(self, db_path: Path, stop=None, wake=None, minutes: float = 15, clock=time.localtime):
        self.db_path, self.stop, self.wake, self.clock = db_path, stop, wake, clock
        self.until = time.monotonic() + minutes * 60
        self._mode, self._checked = None, 0.0

    def allowed_now(self) -> bool:
        if self._mode is None or time.monotonic() - self._checked > 30:
            self._mode, self._checked = mode(self.db_path), time.monotonic()
        return allowed(self._mode, self.clock().tm_hour)

    def is_set(self) -> bool:
        return bool((self.stop is not None and self.stop.is_set()) or (self.wake is not None and self.wake.is_set())
                    or time.monotonic() > self.until or not self.allowed_now())
