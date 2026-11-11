"""Lossless files that were really made from an MP3 or AAC ("fake FLAC").

A lossy encoder throws away the treble the ear hears least: above a cut-off (about 16 kHz for a
128 kbps MP3, 19–20 kHz for the best ones) the sound stops dead. Turning that file into FLAC
keeps the gap. A real CD rip carries on to 20–22 kHz, and an old or soft recording with little
treble fades away gently instead of stopping.

So: the average spectrum of half a minute from the middle of the song, in 200 Hz bands, and the
biggest drop from the kilohertz below a point to (nearly) everything above it. A drop of 25 dB
or more is a cut-off; below 19 kHz it's a lossy encoder's, as no lossless master stops there.
The best MP3s (320 kbps, cut at 19–20 kHz) can pass for lossless; this only flags what surely isn't.
"""

from __future__ import annotations

import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from . import procs
from .db import session
from .smart import LOSSLESS

log = logging.getLogger("shelf.lossy")

SECONDS = 30
N_FFT = 8192
BAND = 200.0  # Hz
LOWEST = 11_000.0  # no encoder cuts lower than this
DROP_DB = 25.0
LOSSY_BELOW = 19_000.0  # Hz: real lossless masters don't stop dead below this


def _audio(path: Path, duration: float) -> tuple[np.ndarray, int] | None:
    """Mono audio from the middle of the song, at the file's own sample rate."""
    start = max(0.0, duration * 0.4 - SECONDS / 2) if duration > SECONDS * 1.5 else 0.0
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=sample_rate",
                            "-of", "csv=p=0", str(path)], capture_output=True, timeout=60, **procs.no_window())
    try:
        sr = int(probe.stdout.decode().strip().splitlines()[0])
    except (ValueError, IndexError):
        return None
    raw = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{start:.1f}", "-t", str(SECONDS), "-i", str(path),
         "-map", "0:a:0", "-ac", "1", "-f", "f32le", "-"],
        capture_output=True, timeout=300, **procs.no_window(),
    ).stdout
    y = np.frombuffer(raw, dtype=np.float32)
    return (y, sr) if len(y) >= sr * 5 else None


def _band_levels(y: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    """The average power in each 200 Hz band, in dB, and each band's lower edge."""
    window = np.hanning(N_FFT).astype(np.float32)
    frames = np.lib.stride_tricks.sliding_window_view(y, N_FFT)[::N_FFT // 2]
    power = np.zeros(N_FFT // 2 + 1)
    for i in range(0, len(frames), 256):
        power += (np.abs(np.fft.rfft(frames[i:i + 256] * window, axis=1)) ** 2).sum(axis=0)
    freqs = np.fft.rfftfreq(N_FFT, 1 / sr)
    edges = np.arange(0, sr / 2, BAND)
    idx = np.clip(np.searchsorted(edges, freqs, side="right") - 1, 0, len(edges) - 1)
    bands = np.bincount(idx, weights=power, minlength=len(edges)) / np.maximum(np.bincount(idx, minlength=len(edges)), 1)
    return 10 * np.log10(bands + 1e-20), edges


def cutoff_of(levels: np.ndarray, edges: np.ndarray) -> float | None:
    """Where the sound stops dead (Hz), or None if it doesn't (it goes on, or fades away)."""
    best, at = 0.0, None
    top = len(edges) - 2  # the last band runs into the anti-alias filter
    for k in range(int(LOWEST // BAND), top):
        below = np.median(levels[max(0, k - 5):k])
        above = np.percentile(levels[k:top + 1], 90)
        if below - above > best:
            best, at = below - above, k
    if at is None or best < DROP_DB:
        return None
    if levels[:at].max() < -100:  # silence
        return None
    return float(edges[at])


def cutoff(path: Path, duration: float) -> float | None:
    got = _audio(path, duration)
    if got is None:
        return None
    return cutoff_of(*_band_levels(*got))


def looks_lossy(cut: float | None) -> bool:
    return cut is not None and cut < LOSSY_BELOW


def likely_source(cut: float) -> str:
    """What made a file cut off there, in words."""
    if cut < 15_000:
        return "a low-quality MP3 or AAC (under 128 kbps)"
    if cut < 17_000:
        return "a 128 kbps MP3 or AAC"
    return "an MP3 or AAC of 160 kbps or more"


def check_pending(db_path: Path, stop=None, workers: int = 2) -> int:
    """Checks lossless files not checked yet (or changed since). Returns how many were checked."""
    with session(db_path) as conn:
        rows = [r for r in conn.execute("SELECT id, path, duration, codec FROM tracks WHERE cutoff_checked = 0 ORDER BY id")
                if (r["codec"] or "").lower().startswith(LOSSLESS)]
    if not rows:
        return 0
    log.info("Checking %d lossless files for a lossy past", len(rows))

    def one(r):
        try:
            return cutoff(Path(r["path"]), r["duration"] or 0)
        except (subprocess.SubprocessError, OSError, ValueError):
            return None

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(one, r): r["id"] for r in rows}
        for fut in futures:
            if stop is not None and stop.is_set():
                pool.shutdown(wait=False, cancel_futures=True)
                break
            cut = fut.result()
            with session(db_path) as conn:
                conn.execute("UPDATE tracks SET cutoff = ?, cutoff_checked = 1 WHERE id = ?", (cut, futures[fut]))
            done += 1
    return done
