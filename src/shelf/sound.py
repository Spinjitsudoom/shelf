"""How songs sound, for "sounds like" in recommendations, radio and mixes.

Each song gets a fingerprint of about fifty numbers, measured once in the background from a
minute in its middle: its tone colour (MFCCs, average and spread), how bright and how noisy
it is, the contrast between peaks and valleys across the spectrum, how its loudness moves,
how danceable it is and how busy (onsets per second). Two songs sound alike when their
fingerprints point the same way once every number is scaled against the whole library.

Like tempo and key, each song is measured in its own low-priority process.

Run directly to measure one file:  python -m shelf.sound song.flac
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import procs
from .db import session

log = logging.getLogger("shelf.sound")

VERSION = 1
SR = 22050
SECONDS = 60


def version() -> int:
    """What sound_checked holds once a song is measured: it differs per engine, because Essentia's
    fingerprints and the numpy engine's can't be compared with each other."""
    return VERSION if procs.analysis_engine() == "essentia" else VERSION + 100


def _measure_here(path: str, duration: float) -> list[float] | None:
    if procs.analysis_engine() == "dsp":
        return _measure_dsp(path, duration)
    import numpy as np
    import essentia
    import essentia.standard as es

    essentia.log.infoActive = False
    essentia.log.warningActive = False
    start = max(0.0, duration * 0.35 - SECONDS / 2) if duration > SECONDS * 1.5 else 0.0
    raw = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{start:.1f}", "-t", str(SECONDS), "-i", path,
         "-map", "0:a:0", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
        capture_output=True, timeout=300,
    ).stdout
    audio = np.frombuffer(raw, dtype=np.float32).copy()
    if len(audio) < SR * 10:
        return None

    frame, hop = 2048, 1024
    window = es.Windowing(type="hann")
    spectrum = es.Spectrum()
    mfcc = es.MFCC(inputSize=frame // 2 + 1, sampleRate=SR, numberCoefficients=13)
    centroid = es.Centroid(range=SR / 2)
    rolloff = es.RollOff(sampleRate=SR)
    flatness = es.Flatness()
    flux = es.Flux()
    contrast = es.SpectralContrast(frameSize=frame, sampleRate=SR)
    zcr = es.ZeroCrossingRate()
    rms = es.RMS()

    feats = {"mfcc": [], "centroid": [], "rolloff": [], "flatness": [], "flux": [], "zcr": [], "rms": [],
             "contrast": [], "valley": []}
    for f in es.FrameGenerator(audio, frameSize=frame, hopSize=hop, startFromZero=True):
        r = rms(f)
        if r < 1e-4:  # silence says nothing about how it sounds
            continue
        spec = spectrum(window(f))
        _, coeffs = mfcc(spec)
        c, v = contrast(spec)
        feats["mfcc"].append(coeffs)
        feats["centroid"].append(centroid(spec))
        feats["rolloff"].append(rolloff(spec))
        feats["flatness"].append(flatness(spec + 1e-12))
        feats["flux"].append(flux(spec))
        feats["zcr"].append(zcr(f))
        feats["rms"].append(20 * np.log10(r + 1e-9))
        feats["contrast"].append(c)
        feats["valley"].append(v)
    if len(feats["mfcc"]) < 50:
        return None
    m = np.array(feats["mfcc"])
    vec = list(m.mean(axis=0)) + list(m.std(axis=0))
    for k in ("centroid", "rolloff", "flatness", "flux", "zcr", "rms"):
        a = np.array(feats[k])
        vec += [float(a.mean()), float(a.std())]
    vec += list(np.array(feats["contrast"]).mean(axis=0)) + list(np.array(feats["valley"]).mean(axis=0))
    dance, _ = es.Danceability(sampleRate=SR)(audio)
    onsets = es.OnsetRate()(es.Resample(inputSampleRate=SR, outputSampleRate=44100)(audio))[1]
    vec += [float(dance), float(onsets)]
    return [round(float(x), 5) for x in vec]


def _measure_dsp(path: str, duration: float) -> list[float] | None:
    import numpy as np
    from . import dsp

    start = max(0.0, duration * 0.35 - SECONDS / 2) if duration > SECONDS * 1.5 else 0.0
    raw = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{start:.1f}", "-t", str(SECONDS), "-i", path,
         "-map", "0:a:0", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
        capture_output=True, timeout=300, **procs.no_window(),
    ).stdout
    audio = np.frombuffer(raw, dtype=np.float32).copy()
    if len(audio) < SR * 10:
        return None
    return dsp.features(audio, SR)


def counts(db_path: Path) -> tuple[int, int]:
    """(measured with this server's engine, all songs)."""
    with session(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
        done = conn.execute("SELECT COUNT(*) FROM tracks WHERE sound_checked = ?", (version(),)).fetchone()[0]
    return done, total


def measure(path: Path, duration: float) -> list[float] | None:
    """One file's fingerprint, measured in a separate process. None if it failed."""
    try:
        out = subprocess.run(
            procs.python_module("shelf.sound", str(path), str(duration)),
            capture_output=True, timeout=300, **procs.low_priority(),
        )
        if out.returncode != 0:
            return None
        res = json.loads(out.stdout.decode().strip().splitlines()[-1])
        return res if isinstance(res, list) else None
    except (subprocess.SubprocessError, OSError, ValueError, IndexError):
        return None


def analyze_pending(db_path: Path, stop=None, workers: int = 2) -> int:
    current = version()
    with session(db_path) as conn:
        # Fingerprints from the other engine go at once, so the two are never compared.
        conn.execute("UPDATE tracks SET sound = NULL WHERE sound_checked NOT IN (0, ?)", (current,))
        rows = conn.execute("SELECT id, path, duration FROM tracks WHERE sound_checked != ? ORDER BY id",
                            (current,)).fetchall()
    if not rows:
        return 0
    log.info("Measuring how %d tracks sound", len(rows))
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(measure, Path(r["path"]), r["duration"] or 0): r["id"] for r in rows}
        for fut in futures:
            if stop is not None and stop.is_set():
                pool.shutdown(wait=False, cancel_futures=True)
                break
            vec = fut.result()
            with session(db_path) as conn:
                conn.execute("UPDATE tracks SET sound = ?, sound_checked = ? WHERE id = ?",
                             (json.dumps(vec) if vec else None, current, futures[fut]))
            done += 1
    log.info("Measured how %d tracks sound", done)
    return done


# ---------- similarity ----------

_cache: dict = {"key": None, "vectors": {}}
_lock = threading.Lock()


def vectors(rows) -> dict[int, "object"]:
    """Every measured song's fingerprint, each number scaled against the library (z-scores)
    and the whole made unit length, by track id. Cached until the library changes."""
    import numpy as np

    measured = [r for r in rows if r["sound"]]
    key = (len(measured), sum(r["id"] for r in measured))
    with _lock:
        if _cache["key"] == key:
            return _cache["vectors"]
    if len(measured) < 10:
        out: dict = {}
    else:
        ids = [r["id"] for r in measured]
        m = np.array([json.loads(r["sound"]) for r in measured], dtype=float)
        m = (m - m.mean(axis=0)) / (m.std(axis=0) + 1e-9)
        m /= np.linalg.norm(m, axis=1, keepdims=True) + 1e-9
        out = dict(zip(ids, m))
    with _lock:
        _cache["key"] = key
        _cache["vectors"] = out
        _cache["matrix"] = m if out else None
        _cache["ids"] = ids if out else []
        _cache["pos"] = {i: n for n, i in enumerate(ids)} if out else {}
    return out


def library_vectors(db_path) -> dict[int, "object"]:
    """vectors() for the whole library, read from the database only when it's changed."""
    with session(db_path) as conn:
        key = tuple(conn.execute("SELECT COUNT(*), COALESCE(SUM(id), 0) FROM tracks WHERE sound IS NOT NULL").fetchone())
        with _lock:
            if _cache["key"] == key:
                return _cache["vectors"]
        rows = conn.execute("SELECT id, sound FROM tracks WHERE sound IS NOT NULL").fetchall()
    return vectors(rows)


def ranked(vecs: dict, seed_id: int) -> tuple[list[int], "object"]:
    """Every other measured song, and how much each sounds like the seed (-1..1), in the same
    order. Uses the library's matrix when `vecs` is the cached one, instead of building it."""
    import numpy as np

    with _lock:
        cached = _cache["vectors"] is vecs and _cache.get("matrix") is not None
        m, ids = (_cache["matrix"], _cache["ids"]) if cached else (None, None)
    if not cached:
        ids = list(vecs)
        m = np.array([vecs[i] for i in ids]) if ids else np.zeros((0, 1))
    if seed_id not in vecs or not ids:
        return [], np.zeros(0)
    sims = m @ vecs[seed_id]
    keep = np.array([i != seed_id for i in ids])
    return [i for i, k in zip(ids, keep) if k], sims[keep]


def centre(vecs: dict, ids) -> "object | None":
    """The average fingerprint of some songs (unit length), or None if none are measured."""
    import numpy as np

    have = [vecs[i] for i in ids if i in vecs]
    if not have:
        return None
    c = np.mean(have, axis=0)
    n = np.linalg.norm(c)
    return c / n if n else None


def nearest(vecs: dict, mine, candidates) -> dict[int, float]:
    """{candidate: -1..1}: how much each candidate sounds like the songs of `mine` it's closest
    to (the nearest one for a few songs, the nearest few for many). Unlike the average of
    `mine`, this keeps a playlist of thrash and ballads finding both, not their muddy middle."""
    import numpy as np

    have = [vecs[i] for i in mine if i in vecs]
    cand = [i for i in candidates if i in vecs]
    if not have or not cand:
        return {}
    k = min(3, max(1, len(have) // 5))
    with _lock:
        cached = _cache["vectors"] is vecs and _cache.get("matrix") is not None
        m, pos = (_cache["matrix"], _cache["pos"]) if cached else (None, None)
    if cached:  # the whole library's, already in one matrix: take the rows
        rows = m[np.fromiter((pos[i] for i in cand), dtype=np.int64, count=len(cand))]
    else:
        rows = np.array([vecs[i] for i in cand])
    sims = rows @ np.array(have).T
    top = -np.partition(-sims, k - 1, axis=1)[:, :k] if sims.shape[1] > k else sims
    return dict(zip(cand, top.mean(axis=1).tolist()))


def similarity(vecs: dict, centre_vec, track_id: int) -> float:
    """-1..1: how much a song sounds like the centre."""
    v = vecs.get(track_id)
    if v is None or centre_vec is None:
        return 0.0
    return float(v @ centre_vec)


if __name__ == "__main__":
    print(json.dumps(_measure_here(sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 0)))


# Positions in the fingerprint (see _measure_here): RMS level, spectral flux, centroid, danceability, onsets.
_RMS, _FLUX, _CENTROID, _DANCE, _ONSETS = 36, 32, 26, 50, 51
_energy_cache: dict = {"key": None, "energy": {}}


def energy(rows) -> dict[int, float]:
    """How energetic each measured song is, 0 (calmest on the shelf) to 1 (most intense): its
    level, how much it moves, brightness, danceability, busyness and tempo, ranked against the
    rest of the library. Cached until the library changes."""
    import numpy as np

    measured = [r for r in rows if r["sound"]]
    key = (len(measured), sum(r["id"] for r in measured))
    with _lock:
        if _energy_cache["key"] == key:
            return _energy_cache["energy"]
    out: dict[int, float] = {}
    if len(measured) >= 10:
        m = np.array([json.loads(r["sound"]) for r in measured], dtype=float)
        bpm = np.array([r["bpm"] or 0 for r in measured], dtype=float)
        bpm[bpm == 0] = np.median(bpm[bpm > 0]) if (bpm > 0).any() else 120
        z = lambda col: (col - col.mean()) / (col.std() + 1e-9)
        score = z(m[:, _RMS]) + z(m[:, _FLUX]) + z(m[:, _ONSETS]) + 0.5 * z(m[:, _CENTROID]) + 0.5 * z(m[:, _DANCE]) + 0.5 * z(bpm)
        ranks = score.argsort().argsort() / max(1, len(score) - 1)
        out = {r["id"]: round(float(x), 3) for r, x in zip(measured, ranks)}
    with _lock:
        _energy_cache.update(key=key, energy=out)
    return out
