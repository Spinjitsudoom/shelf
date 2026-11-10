"""What suggestions learn from someone: songs they skip (moving on before 30 seconds of it), and
suggestions they add to a playlist and then take back out.

Only the last 90 days count, so a song or artist can come back. A skip counts once, a removed
suggestion twice, up to a limit; an artist with three or more songs turned down sinks a little
too; and a suggestion taken out of a playlist is never suggested for that playlist again.
"""

from __future__ import annotations

DAY = 86400
REMEMBER = 90 * DAY
WEIGHT = {"skip": 1.0, "removed": 2.0}
SONG_MAX = 2.0  # the most a song sinks (suggestions score about 0..10)
ARTIST = 1.0  # how much an artist sinks once three of their songs are turned down


def penalties(rows, now: float, playlist_id: int | None = None):
    """rows: (track_id, folded artist, kind, playlist_id, at). Returns ({song: how much it sinks},
    {artist: how much they sink}, {songs never to suggest for `playlist_id`})."""
    weight: dict[int, float] = {}
    turned_down: dict[str, set[int]] = {}
    banned: set[int] = set()
    for track, artist, kind, pid, at in rows:
        if now - at > REMEMBER or kind not in WEIGHT:
            continue
        weight[track] = weight.get(track, 0.0) + WEIGHT[kind]
        turned_down.setdefault(artist, set()).add(track)
        if kind == "removed" and playlist_id is not None and pid == playlist_id:
            banned.add(track)
    song = {t: SONG_MAX * min(w, 3.0) / 3.0 for t, w in weight.items()}
    artist = {a: ARTIST for a, songs in turned_down.items() if a and len(songs) >= 3}
    return song, artist, banned
