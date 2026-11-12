"""SQLite storage. One connection per call site; WAL lets the scanner write while requests read."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    id           INTEGER PRIMARY KEY,
    path         TEXT NOT NULL UNIQUE,
    mtime        REAL NOT NULL,
    size         INTEGER NOT NULL,
    title        TEXT NOT NULL,
    artist       TEXT NOT NULL,
    album_artist TEXT,
    album        TEXT NOT NULL,
    album_key    TEXT NOT NULL,
    track_no     INTEGER,
    disc_no      INTEGER,
    year         INTEGER,
    genre        TEXT,
    duration     REAL NOT NULL DEFAULT 0,
    codec        TEXT,
    mime         TEXT,
    bitrate      INTEGER,
    sample_rate  INTEGER,
    bits         INTEGER,
    lufs         REAL,
    peak         REAL,
    loud_checked INTEGER NOT NULL DEFAULT 0,
    has_art      INTEGER NOT NULL DEFAULT 0,
    added_at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS tracks_album_key ON tracks(album_key);

CREATE TABLE IF NOT EXISTS albums (
    id          INTEGER PRIMARY KEY,
    key         TEXT NOT NULL UNIQUE,
    title       TEXT NOT NULL,
    artist      TEXT NOT NULL,
    year        INTEGER,
    genre       TEXT,
    track_count INTEGER NOT NULL,
    duration    REAL NOT NULL,
    cover_src   TEXT,
    color       TEXT,
    added_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS albums_artist ON albums(artist COLLATE NOCASE);

-- One row per listen (counted after half the track or 4 minutes, like scrobbling).
-- Keyed by album_key rather than album id so history survives album rebuilds.
CREATE TABLE IF NOT EXISTS plays (
    id         INTEGER PRIMARY KEY,
    track_id   INTEGER NOT NULL,
    album_key  TEXT NOT NULL,
    played_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS plays_album ON plays(album_key, played_at);
CREATE INDEX IF NOT EXISTS plays_time ON plays(played_at);

-- Lyrics looked up online, keyed by artist/title/album/length so rescans don't lose them.
-- Misses are stored too (found = 0) so songs without lyrics aren't looked up every play.
CREATE TABLE IF NOT EXISTS lyrics_cache (
    key          TEXT PRIMARY KEY,
    fetched_at   REAL NOT NULL,
    found        INTEGER NOT NULL,
    synced       TEXT,
    plain        TEXT,
    instrumental INTEGER NOT NULL DEFAULT 0
);

-- YouTube music video found for a song (video_id NULL: looked, found none).
CREATE TABLE IF NOT EXISTS video_cache (
    key        TEXT PRIMARY KEY,
    fetched_at REAL NOT NULL,
    video_id   TEXT,
    title      TEXT,
    channel    TEXT
);

CREATE TABLE IF NOT EXISTS playlists (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);

-- Songs in a playlist, in order. Entries go when the song's file leaves the library.
CREATE TABLE IF NOT EXISTS playlist_tracks (
    id          INTEGER PRIMARY KEY,
    playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    track_id    INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    position    REAL NOT NULL,
    added_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS playlist_tracks_order ON playlist_tracks(playlist_id, position);
CREATE INDEX IF NOT EXISTS playlist_tracks_track ON playlist_tracks(track_id);

-- Things looked up about artists: their Wikipedia summary and their other music videos.
CREATE TABLE IF NOT EXISTS artist_cache (
    key        TEXT NOT NULL,
    kind       TEXT NOT NULL,
    fetched_at REAL NOT NULL,
    data       TEXT,
    PRIMARY KEY (key, kind)
);

-- Favourites (liked songs), per person. A song that leaves the library leaves the list too.
CREATE TABLE IF NOT EXISTS shares (
    token      TEXT PRIMARY KEY,  -- the secret part of the link (/s/<token>)
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,     -- track, album or playlist
    item_id    INTEGER NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL,              -- NULL: never runs out
    opened     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS resume_points (
    user_id    INTEGER NOT NULL,
    track_id   INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    position   REAL NOT NULL,  -- seconds
    comment    TEXT,
    updated_at REAL NOT NULL,
    PRIMARY KEY (user_id, track_id)
);

CREATE TABLE IF NOT EXISTS likes (
    user_id   INTEGER NOT NULL DEFAULT 1,
    track_id  INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    liked_at  REAL NOT NULL,
    PRIMARY KEY (user_id, track_id)
);

-- People who can sign in. Likes, playlists and history belong to one of them (the first
-- account, id 1, keeps whatever was there before accounts existed).
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT NOT NULL UNIQUE COLLATE NOCASE,
    pw_hash     TEXT NOT NULL,
    is_admin    INTEGER NOT NULL DEFAULT 0,
    created_at  REAL NOT NULL,
    last_seen   REAL,
    session_ver INTEGER NOT NULL DEFAULT 1
);

-- Listens waiting to be sent to ListenBrainz.
CREATE TABLE IF NOT EXISTS scrobbles (
    id        INTEGER PRIMARY KEY,
    user_id   INTEGER NOT NULL,
    track_id  INTEGER NOT NULL,
    played_at REAL NOT NULL
);

-- What people do with the DJ: skips, "switch it up", thumbs on what the host said.
-- What suggestions learn from: skips, and suggestions taken back out of a playlist (feedback.py).
CREATE TABLE IF NOT EXISTS feedback (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL,
    track_id    INTEGER NOT NULL,
    kind        TEXT NOT NULL,   -- skip, removed
    playlist_id INTEGER,         -- for removed: the playlist it came out of
    at          REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS feedback_user ON feedback(user_id, at);
CREATE TABLE IF NOT EXISTS dj_feedback (
    id        INTEGER PRIMARY KEY,
    user_id   INTEGER NOT NULL,
    track_id  INTEGER,
    theme     TEXT,
    kind      TEXT NOT NULL,   -- skip, switch, up, down
    text      TEXT,            -- for up/down: the line
    at        REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS dj_feedback_user ON dj_feedback(user_id, at);

-- Someone else's shared playlist, saved to your library.
-- Webhooks: where to tell another program what happens (webhooks.py). Admins add them.
CREATE TABLE IF NOT EXISTS webhooks (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    url         TEXT NOT NULL,
    events      TEXT NOT NULL,           -- JSON list: playing, paused, played, library
    secret      TEXT NOT NULL DEFAULT '',
    created_at  REAL NOT NULL,
    last_at     REAL,
    last_status TEXT
);

CREATE TABLE IF NOT EXISTS playlist_follows (
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    followed_at REAL NOT NULL,
    PRIMARY KEY (user_id, playlist_id)
);

-- Stars on albums and artists from Subsonic apps (a starred song is a like). ref: the album's
-- key, or the artist's folded name, so they last through rescans.
CREATE TABLE IF NOT EXISTS stars (
    user_id INTEGER NOT NULL,
    kind    TEXT NOT NULL,
    ref     TEXT NOT NULL,
    at      REAL NOT NULL,
    PRIMARY KEY (user_id, kind, ref)
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        # Columns added after the first release.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(tracks)")}
        for name, decl in (
            ("bits", "INTEGER"),
            ("lufs", "REAL"),
            ("peak", "REAL"),
            ("loud_checked", "INTEGER NOT NULL DEFAULT 0"),
            ("bpm", "REAL"),
            ("musical_key", "TEXT"),
            ("rhythm_checked", "INTEGER NOT NULL DEFAULT 0"),
            ("mix_points", "TEXT"),  # beats, intro and outro, for Mix (JSON)
            ("sound", "TEXT"),  # how it sounds, for "sounds like" (JSON numbers, see sound.py)
            ("sound_checked", "INTEGER NOT NULL DEFAULT 0"),
            ("cutoff", "REAL"),  # Hz where a lossless file's sound stops dead (made from an MP3?), see lossy.py
            ("cutoff_checked", "INTEGER NOT NULL DEFAULT 0"),
            ("fp", "BLOB"),  # the first minute's audio fingerprint, for finding the same recording twice (fingerprint.py)
            ("fp_checked", "INTEGER NOT NULL DEFAULT 0"),
        ):
            _add_column(conn, "tracks", cols, name, decl)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(playlists)")}
        _add_column(conn, "playlists", cols, "mix", "INTEGER NOT NULL DEFAULT 0")
        # Accounts: what was there before belongs to the first one.
        _add_column(conn, "playlists", cols, "user_id", "INTEGER NOT NULL DEFAULT 1")
        # Sharing: 0 private, 1 public (others can play and follow it), 2 collaborative (and add songs).
        _add_column(conn, "playlists", cols, "shared", "INTEGER NOT NULL DEFAULT 0")
        # A smart playlist: rules (JSON, see smart.py) pick its songs instead of playlist_tracks.
        _add_column(conn, "playlists", cols, "rules", "TEXT")
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(playlist_tracks)")}
        _add_column(conn, "playlist_tracks", cols, "added_by", "INTEGER")
        _add_column(conn, "playlist_tracks", cols, "suggested", "INTEGER NOT NULL DEFAULT 0")  # added from its suggestions
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
        _add_column(conn, "users", cols, "share_activity", "INTEGER NOT NULL DEFAULT 1")
        _add_column(conn, "users", cols, "listenbrainz_token", "TEXT")
        _add_column(conn, "users", cols, "listenbrainz_user", "TEXT")
        _add_column(conn, "users", cols, "lastfm_session", "TEXT")
        _add_column(conn, "users", cols, "lastfm_user", "TEXT")
        _add_column(conn, "users", cols, "lastfm_token", "TEXT")  # waiting to be approved on last.fm
        _add_column(conn, "users", cols, "subsonic_secret", "TEXT")  # the app password for Subsonic apps, sealed
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(scrobbles)")}
        _add_column(conn, "scrobbles", cols, "service", "TEXT NOT NULL DEFAULT 'listenbrainz'")
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(plays)")}
        _add_column(conn, "plays", cols, "user_id", "INTEGER NOT NULL DEFAULT 1")
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(likes)")}
        if "user_id" not in cols:  # liked songs were keyed by song alone
            conn.executescript("""
                CREATE TABLE likes_new (
                    user_id INTEGER NOT NULL DEFAULT 1,
                    track_id INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
                    liked_at REAL NOT NULL,
                    PRIMARY KEY (user_id, track_id));
                INSERT INTO likes_new(user_id, track_id, liked_at) SELECT 1, track_id, liked_at FROM likes;
                DROP TABLE likes;
                ALTER TABLE likes_new RENAME TO likes;
            """)
        conn.executescript("""
            CREATE INDEX IF NOT EXISTS likes_time ON likes(user_id, liked_at);
            CREATE INDEX IF NOT EXISTS plays_user ON plays(user_id, played_at);
            CREATE INDEX IF NOT EXISTS playlists_user ON playlists(user_id, updated_at);
        """)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(playlist_tracks)")}
        # How this song hands over to the next one in Mix: auto, blend, swap, rise, fade or cut.
        _add_column(conn, "playlist_tracks", cols, "transition", "TEXT")


def _add_column(conn, table: str, existing: set[str], name: str, decl: str) -> None:
    if name in existing:
        return
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
    except sqlite3.OperationalError as e:  # another process added it first
        if "duplicate column" not in str(e):
            raise


@contextmanager
def session(db_path: Path):
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
