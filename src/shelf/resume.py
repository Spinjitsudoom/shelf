"""Where each person stopped in a long track (a live set, a DJ mix, an audiobook), so it picks up
there next time. The players decide which tracks are long enough to keep a place for; Subsonic
apps' bookmarks are the same places.
"""

from __future__ import annotations

import time

START = 10.0  # seconds: before this it's the start, nothing to keep
END = 30.0  # seconds from the end: finished, start over next time


def get(conn, user_id: int, track_id: int) -> float:
    row = conn.execute("SELECT position FROM resume_points WHERE user_id = ? AND track_id = ?", (user_id, track_id)).fetchone()
    return row["position"] if row else 0.0


def put(conn, user_id: int, track_id: int, position: float, duration: float, comment: str | None = None) -> None:
    """Keeps a place; the start or the end (finished) forgets it."""
    if position < START or (duration and position > duration - END):
        forget(conn, user_id, track_id)
        return
    conn.execute(
        "INSERT INTO resume_points(user_id, track_id, position, comment, updated_at) VALUES(?, ?, ?, ?, ?)"
        " ON CONFLICT(user_id, track_id) DO UPDATE SET position = excluded.position,"
        " comment = COALESCE(excluded.comment, resume_points.comment), updated_at = excluded.updated_at",
        (user_id, track_id, float(position), comment, time.time()),
    )


def forget(conn, user_id: int, track_id: int) -> None:
    conn.execute("DELETE FROM resume_points WHERE user_id = ? AND track_id = ?", (user_id, track_id))


def all_for(conn, user_id: int) -> list:
    return conn.execute("SELECT track_id, position, comment, updated_at FROM resume_points WHERE user_id = ?"
                        " ORDER BY updated_at DESC", (user_id,)).fetchall()
