"""Things that keep a big library quick."""

from shelf.db import TRACK_COLUMNS, session


def test_track_columns_are_every_column_but_the_fingerprint(client):
    with session(client.app.state.cfg.db_path) as conn:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(tracks)")]
    assert [c.strip() for c in TRACK_COLUMNS.split(",")] == [c for c in cols if c != "fp"]
