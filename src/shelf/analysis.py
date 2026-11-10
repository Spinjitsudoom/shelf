"""Tempo (BPM) and musical key, measured in the background like loudness.

Essentia does the listening: RhythmExtractor2013 for the tempo and KeyExtractor with the
"edma" profile (made for popular and electronic music) for the key. Each song is analyzed
in its own low-priority process, so a crash in the audio library can't take the server down.

Keys are shown in Camelot notation (8A, 8B...) as DJ software does: neighbouring numbers,
and the same number with A/B, are keys that mix well together.

For Mix (DJ-style transitions) each song also gets its "mix points": where the sound
starts and ends, where the full-energy part begins (intro) and winds down (outro), its first
beat, and a beat near the outro with the local beat length there, so the next song can be
lined up on the beat even when a live drummer's tempo drifts.

Run directly to analyze one file:  python -m shelf.analysis song.flac
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import procs
from .db import session

log = logging.getLogger("shelf.analysis")

VERSION = 2  # rhythm_checked value once a song has tempo, key and mix points
MAX_SECONDS = 420  # tempo and key: the first 7 minutes are plenty
MAX_DECODE = 1800  # mix points need the whole song (up to 30 minutes)
SR = 44100
_NOTE = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6,
         "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}
_NAMES = ["C", "D♭", "D", "E♭", "E", "F", "F♯", "G", "A♭", "A", "B♭", "B"]
# Camelot numbers by pitch class, for major (B) and minor (A) keys.
_CAMELOT_MAJOR = {0: 8, 7: 9, 2: 10, 9: 11, 4: 12, 11: 1, 6: 2, 1: 3, 8: 4, 3: 5, 10: 6, 5: 7}
_CAMELOT_MINOR = {9: 8, 4: 9, 11: 10, 6: 11, 1: 12, 8: 1, 3: 2, 10: 3, 5: 4, 0: 5, 7: 6, 2: 7}


def normalize_key(note: str, scale: str) -> str | None:
    """Essentia's ("Bb", "minor") as "B♭ minor"."""
    pc = _NOTE.get(note)
    if pc is None or scale not in ("major", "minor"):
        return None
    return f"{_NAMES[pc]} {scale}"


def camelot(key: str | None) -> str | None:
    """"A minor" -> "8A", "C major" -> "8B"."""
    if not key:
        return None
    try:
        name, scale = key.rsplit(" ", 1)
        pc = _NAMES.index(name)
    except ValueError:
        return None
    return f"{_CAMELOT_MAJOR[pc]}B" if scale == "major" else f"{_CAMELOT_MINOR[pc]}A"


def camelot_neighbours(code: str) -> set[str]:
    """Keys that mix well with `code`: itself, one step either way, and its relative."""
    n, letter = int(code[:-1]), code[-1]
    other = "A" if letter == "B" else "B"
    return {code, f"{(n % 12) + 1}{letter}", f"{((n - 2) % 12) + 1}{letter}", f"{n}{other}"}


def _analyze_here(path: str) -> dict:
    if procs.analysis_engine() == "dsp":
        return _analyze_dsp(path)
    import numpy as np
    import essentia
    import essentia.standard as es

    essentia.log.infoActive = False
    essentia.log.warningActive = False
    raw = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", path, "-t", str(MAX_DECODE), "-map", "0:a:0",
         "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
        capture_output=True, timeout=600,
    ).stdout
    song = np.frombuffer(raw, dtype=np.float32).copy()
    if len(song) < SR * 5:
        return {"bpm": None, "key": None, "mix": None}
    audio = song[: SR * MAX_SECONDS]
    rhythm = es.RhythmExtractor2013(method="multifeature")
    bpm, beats, _conf, _, _ = rhythm(audio)
    note, scale, strength = es.KeyExtractor(profileType="edma")(audio)
    bpm = float(bpm) if bpm and 30 < bpm < 260 else None
    return {
        "bpm": round(bpm, 1) if bpm else None,
        "key": normalize_key(note, scale) if strength > 0.1 else None,
        "mix": mix_points(song, np.asarray(beats, dtype=float), bpm, rhythm),
    }


def _analyze_dsp(path: str) -> dict:
    """The same measurements with Shelf's numpy engine (no Essentia, e.g. on Windows). It works
    at half the rate: averaging sample pairs is plenty for beats and notes."""
    import numpy as np
    from . import dsp

    raw = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", path, "-t", str(MAX_DECODE), "-map", "0:a:0",
         "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
        capture_output=True, timeout=600, **procs.no_window(),
    ).stdout
    song = np.frombuffer(raw, dtype=np.float32).copy()
    if len(song) < SR * 5:
        return {"bpm": None, "key": None, "mix": None}
    half = lambda a: (a[0: len(a) // 2 * 2: 2] + a[1: len(a) // 2 * 2: 2]) / 2
    audio = half(song[: SR * MAX_SECONDS])
    bpm, beats = dsp.tempo_and_beats(audio, SR // 2)
    note, scale, strength = dsp.key(audio, SR // 2)
    bpm = float(bpm) if bpm and 30 < bpm < 260 else None
    rhythm = lambda seg: dsp.tempo_and_beats(half(seg), SR // 2)
    return {
        "bpm": round(bpm, 1) if bpm else None,
        "key": normalize_key(note, scale) if strength > 0.1 else None,
        "mix": mix_points(song, beats, bpm, rhythm),
    }


def _median_gap(beats, period_hint):
    gaps = [b - a for a, b in zip(beats, beats[1:])]
    if not gaps:
        return period_hint
    gaps.sort()
    return gaps[len(gaps) // 2]


def mix_points(song, beats, bpm, rhythm=None) -> dict:
    """Where a song can be mixed: see the module docstring. Times in seconds."""
    import numpy as np

    hop = SR // 4  # quarter-second frames
    n = len(song) // hop
    frames = song[: n * hop].reshape(n, hop)
    db = 20 * np.log10(np.sqrt((frames.astype(np.float64) ** 2).mean(axis=1)) + 1e-9)
    top = float(np.percentile(db, 95))
    audible = np.nonzero(db > top - 45)[0]
    if not len(audible):
        return None
    start, end = audible[0] / 4, (audible[-1] + 1) / 4
    # Loudness over 4 seconds; the "body" of the song is its typical level while audible.
    smooth = np.convolve(db, np.ones(16) / 16, mode="same")
    body = float(np.median(smooth[audible[0]: audible[-1] + 1]))
    loud = np.nonzero(smooth > body - 6)[0]
    intro = loud[0] / 4 if len(loud) else start
    outro = (loud[-1] + 1) / 4 if len(loud) else end
    outro = min(max(outro, intro), end)

    period = 60 / bpm if bpm else None
    out = {"start": start, "end": end, "intro": intro, "outro": outro,
           "firstBeat": None, "inPeriod": period, "outBeat": None, "outPeriod": period}
    if period and len(beats):
        later = beats[beats >= start - 0.05]
        if len(later):
            out["firstBeat"] = float(later[0])
            out["inPeriod"] = _median_gap([float(b) for b in later if b < later[0] + 30], period)
        # Beats around the outro: from the main analysis if it got that far, otherwise
        # measured again on that stretch.
        lo, hi = max(start, outro - 45), min(end, outro + 15)
        near = [float(b) for b in beats if lo <= b <= hi]
        if (not near or hi > MAX_SECONDS - 1) and rhythm is not None and hi - lo > 10:
            seg = song[int(lo * SR): int(hi * SR)]
            _b, seg_beats, *_ = rhythm(seg)
            near = [lo + float(b) for b in seg_beats]
        if near:
            before = [b for b in near if b <= outro] or near
            out["outBeat"] = before[-1]
            out["outPeriod"] = _median_gap(near, period)
    return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in out.items()}


def analyze(path: Path) -> dict | None:
    """Tempo and key of one file, measured in a separate process. None if it failed."""
    try:
        out = subprocess.run(
            procs.python_module("shelf.analysis", str(path)),
            capture_output=True, timeout=600, **procs.low_priority(),
        )
        return json.loads(out.stdout.decode().strip().splitlines()[-1]) if out.returncode == 0 else None
    except (subprocess.SubprocessError, OSError, ValueError, IndexError):
        return None


def counts(db_path: Path) -> tuple[int, int]:
    with session(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
        done = conn.execute("SELECT COUNT(*) FROM tracks WHERE rhythm_checked >= ?", (VERSION,)).fetchone()[0]
    return done, total


def analyze_pending(db_path: Path, stop=None, workers: int = 2) -> int:
    with session(db_path) as conn:
        rows = conn.execute("SELECT id, path FROM tracks WHERE rhythm_checked < ? ORDER BY id", (VERSION,)).fetchall()
    if not rows:
        return 0
    log.info("Measuring tempo, key and mix points of %d tracks", len(rows))
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(analyze, Path(r["path"])): r["id"] for r in rows}
        for fut in futures:
            if stop is not None and stop.is_set():
                pool.shutdown(wait=False, cancel_futures=True)
                break
            res = fut.result() or {}
            with session(db_path) as conn:
                conn.execute(
                    "UPDATE tracks SET bpm = ?, musical_key = ?, mix_points = ?, rhythm_checked = ? WHERE id = ?",
                    (res.get("bpm"), res.get("key"), json.dumps(res["mix"]) if res.get("mix") else None,
                     VERSION, futures[fut]),
                )
            done += 1
    log.info("Tempo and key measured for %d tracks", done)
    return done


if __name__ == "__main__":
    print(json.dumps(_analyze_here(sys.argv[1])))
