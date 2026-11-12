"""The same recording twice, found by its sound (an audio fingerprint), whatever the files are
called: a FLAC and an MP3 of one song, a copy with no tags, a rip with a second of silence first."""

import subprocess

import numpy as np
import pytest

from shelf import fingerprint as fpm

# A tune: a different note each half second, so the fingerprint changes as it goes.
TUNE = "aevalsrc='0.4*sin(2*PI*(220*pow(2\\,mod(floor(t*2)*5\\,12)/12))*t)':s=44100:d={d}"

RNG = np.random.default_rng(7)


def song(n=460):
    return RNG.integers(0, 2**32, n, dtype=np.uint64).astype(np.uint32)


def copy(a, flip=0.04, shift=0):
    """`a` as another encode would print it: some bits flipped, maybe starting later."""
    b = a.copy()
    bits = RNG.random((len(b), 32)) < flip
    b ^= np.packbits(bits, axis=1, bitorder="little").view("<u4").ravel()
    return np.concatenate([song(shift), b]) if shift else b


def test_same_sound_different_names():
    a, other = song(), song()
    fps = {1: a, 2: copy(a), 3: copy(a, shift=13), 4: other}
    durations = {1: 200, 2: 200.4, 3: 201.7, 4: 200}
    assert fpm.groups(fps, durations) == [[1, 2, 3]]


def test_different_songs_stay_apart():
    fps = {i: song() for i in range(1, 30)}
    assert fpm.groups(fps, {i: 200 for i in fps}) == []


def test_an_edit_is_not_the_same_recording():
    # A radio edit starts the same but is a minute shorter.
    a = song()
    assert fpm.groups({1: a, 2: copy(a)}, {1: 240, 2: 180}) == []


def test_silence_doesnt_make_songs_alike():
    # Long quiet stretches print the same values in many songs; those mustn't pair songs up.
    quiet = np.full(200, 0x5A5A5A5A, dtype=np.uint32)
    fps = {i: np.concatenate([quiet, song(260)]) for i in range(1, 50)}
    assert fpm.groups(fps, {i: 200 for i in fps}) == []
    few = {i: np.concatenate([quiet, quiet, song(100)]) for i in range(1, 6)}  # mostly silence, and only a few
    assert fpm.groups(few, {i: 200 for i in few}) == []


def test_too_short_to_tell():
    a = song(20)
    assert fpm.groups({1: a, 2: a.copy()}, {1: 3, 2: 3}) == []


def test_bit_error_rate():
    a = song()
    assert fpm.distance(a, a, 0) == 0
    assert fpm.distance(a, copy(a, flip=0.05), 0) == pytest.approx(0.05, abs=0.01)
    assert fpm.distance(a, song(), 0) == pytest.approx(0.5, abs=0.03)


def test_fingerprint_of_a_real_file(tmp_path):
    path = tmp_path / "tone.flac"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", TUNE.format(d=20), str(path)], check=True)
    mp3 = tmp_path / "tone.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-b:a", "128k", str(mp3)], check=True)
    a, b = fpm.fingerprint(path), fpm.fingerprint(mp3)
    assert a is not None and len(fpm.decode(a)) > 100
    assert fpm.distance(fpm.decode(a), fpm.decode(b), 0) < 0.2


def test_health_reports_the_same_recording_named_differently(client, library):
    """Through the server: an untagged copy of a song is found once the fingerprints are in."""
    from shelf.db import session

    tagged = library / "Band" / "Single" / "01 Noise.mp3"
    tagged.parent.mkdir(parents=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", TUNE.format(d=20),
                    "-metadata", "title=Noise", "-metadata", "artist=Band", "-metadata", "album=Single", str(tagged)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(tagged), "-map_metadata", "-1", "-c:a", "flac",
                    str(library / "untitled.flac")], check=True)
    app = client.app
    app.state.scanner.run_once()
    db = app.state.scanner.cfg.db_path
    fpm.check_pending(db)
    with session(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM tracks WHERE fp_checked = 0").fetchone()[0] == 0
    assert client.post("/api/login", json={"username": "admin", "password": "hunter2"}).status_code == 200
    r = client.get("/api/admin/health").json()
    titles = [sorted(c["title"] for c in g["copies"]) for g in r["sameAudio"]]
    assert titles == [["Noise", "untitled"]]  # the fixture's 2-second songs are too short to tell apart
    assert r["fingerprints"]["checked"] == r["fingerprints"]["total"]
