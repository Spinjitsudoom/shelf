"""Measuring songs without Essentia (as on Windows), and never mixing the two engines' fingerprints."""

import json
import wave

import numpy as np

from shelf import analysis, procs, sound
from shelf.db import session
from test_dsp import clicks


def write_wav(path, y, sr):
    pcm = (np.clip(y, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def test_engine_choice(monkeypatch):
    monkeypatch.setenv("SHELF_ANALYSIS_ENGINE", "dsp")
    assert procs.analysis_engine() == "dsp"
    monkeypatch.delenv("SHELF_ANALYSIS_ENGINE")
    monkeypatch.setattr(procs, "has_essentia", lambda: False)
    assert procs.analysis_engine() == "dsp"  # Windows
    monkeypatch.setattr(procs, "has_essentia", lambda: True)
    assert procs.analysis_engine() == "essentia"


def test_analysis_without_essentia(tmp_path, monkeypatch):
    monkeypatch.setenv("SHELF_ANALYSIS_ENGINE", "dsp")
    rng = np.random.default_rng(3)
    y = clicks(120, seconds=40, sr=44100) + 0.002 * rng.standard_normal(44100 * 40).astype(np.float32)
    path = tmp_path / "clicks.wav"
    write_wav(path, y, 44100)

    res = analysis._analyze_here(str(path))
    assert abs(res["bpm"] - 120) < 3, res
    assert res["mix"] and res["mix"]["firstBeat"] is not None and abs(res["mix"]["inPeriod"] - 0.5) < 0.01, res

    vec = sound._measure_here(str(path), 40.0)
    assert vec is not None and len(vec) == 52


def test_sound_engine_switch_remeasures(client, monkeypatch):
    db = client.app.state.cfg.db_path
    with session(db) as conn:
        total = conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
        conn.execute("UPDATE tracks SET sound = ?, sound_checked = 1", (json.dumps([0.5] * 52),))  # Essentia's
    measured = []
    monkeypatch.setattr(sound, "measure", lambda path, duration: measured.append(path) or [1.0] * 52)

    monkeypatch.setattr(procs, "analysis_engine", lambda: "dsp")
    assert sound.analyze_pending(db) == total  # another engine: everything again
    with session(db) as conn:
        assert {r[0] for r in conn.execute("SELECT sound_checked FROM tracks")} == {sound.version()}
    assert sound.analyze_pending(db) == 0  # and once is enough
    assert sound.counts(db) == (total, total)

    monkeypatch.setattr(procs, "analysis_engine", lambda: "essentia")
    assert sound.counts(db) == (0, total)
    assert sound.analyze_pending(db) == total
