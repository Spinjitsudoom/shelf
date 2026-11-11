"""Lossless files that were made from an MP3 or AAC: the cut-off a lossy encoder leaves in the sound."""

import subprocess

from shelf import health, lossy
from shelf.db import init_db, session


def make(path, filters="", via_mp3=None, seconds=40):
    """Noise as a FLAC file; via_mp3="128k" first squeezes it through an MP3 of that bitrate."""
    src = f"anoisesrc=color=pink:duration={seconds}:sample_rate=44100:amplitude=0.3"
    if via_mp3:
        mp3 = path.with_suffix(".mp3")
        # Stereo, as real MP3s are: a mono 128 kbps MP3 is as good as a stereo 256 kbps one.
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", src, "-ac", "2", "-b:a", via_mp3, str(mp3)], check=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(mp3), str(path)], check=True)
    else:
        args = ["-af", filters] if filters else []
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", src, *args, str(path)], check=True)
    return path


def test_an_mp3_made_into_flac_is_caught(tmp_path):
    cut = lossy.cutoff(make(tmp_path / "fake.flac", via_mp3="128k"), 40)
    assert cut is not None and 14_500 < cut < 17_500, cut
    assert lossy.looks_lossy(cut)
    assert "128 kbps" in lossy.likely_source(cut)


def test_a_real_lossless_file_passes(tmp_path):
    cut = lossy.cutoff(make(tmp_path / "real.flac"), 40)
    assert not lossy.looks_lossy(cut), cut


def test_a_gentle_roll_off_is_not_a_cut(tmp_path):
    """Old or soft recordings have little treble, but it fades away; it doesn't stop dead."""
    cut = lossy.cutoff(make(tmp_path / "soft.flac", filters="lowpass=f=5000:p=1,lowpass=f=5000:p=1"), 40)
    assert not lossy.looks_lossy(cut), cut


def add(conn, tid, codec, cutoff=None, checked=0, path=None):
    conn.execute("INSERT INTO albums(key, title, artist, track_count, duration, added_at) VALUES('k', 'Album', 'Band', 0, 0, 0)"
                 " ON CONFLICT DO NOTHING")
    conn.execute("INSERT INTO tracks(id, path, mtime, size, title, artist, album, album_key, duration, codec, cutoff, cutoff_checked, added_at)"
                 " VALUES(?, ?, 0, 1, ?, 'Band', 'Album', 'k', 40, ?, ?, ?, 0)",
                 (tid, path or f"/m/{tid}.{codec}", f"Song {tid}", codec, cutoff, checked))


def test_checks_only_lossless_files_once(tmp_path):
    db = tmp_path / "library.db"
    init_db(db)
    fake = make(tmp_path / "fake.flac", via_mp3="128k")
    with session(db) as conn:
        add(conn, 1, "flac", path=str(fake))
        add(conn, 2, "mp3", path=str(tmp_path / "missing.mp3"))
    assert lossy.check_pending(db) == 1
    assert lossy.check_pending(db) == 0
    with session(db) as conn:
        rows = {r["id"]: r for r in conn.execute("SELECT id, cutoff, cutoff_checked FROM tracks")}
    assert rows[1]["cutoff_checked"] and 14_500 < rows[1]["cutoff"] < 17_500
    assert not rows[2]["cutoff_checked"]


def test_health_lists_lossless_files_that_look_converted(tmp_path):
    db = tmp_path / "library.db"
    init_db(db)
    with session(db) as conn:
        add(conn, 1, "flac", cutoff=16_000, checked=1)
        add(conn, 2, "flac", cutoff=None, checked=1)  # sound all the way up
        add(conn, 3, "mp3", cutoff=16_000, checked=1)  # an MP3 is meant to sound like one
        add(conn, 4, "flac", checked=0)  # not checked yet
        r = health.report(conn, lambda src: None, [])
    assert [(t["id"], t["cutoff"]) for t in r["fakeLossless"]] == [(1, 16_000)]
    assert "128 kbps" in r["fakeLossless"][0]["likely"]
    assert r["lossless"] == {"checked": 2, "total": 3}
