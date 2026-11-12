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


def gate(db_path: Path, stop=None, clock=time.localtime, check_every: float = 60.0):
    """A wait each measuring job makes before it starts: it returns at once in allowed hours,
    and otherwise when they come round (or the server is stopping)."""
    def wait() -> None:
        while not allowed(mode(db_path), clock().tm_hour):
            if stop is not None:
                if stop.wait(check_every):
                    return
            else:
                time.sleep(check_every)
    return wait
