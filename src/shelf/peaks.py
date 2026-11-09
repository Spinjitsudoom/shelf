"""Waveforms for the transition editor: how loud a stretch of a song is, moment to moment,
overall and in the bass, so the editor can draw both songs the way DJ software does.

Decoded with ffmpeg at a low sample rate (only the shape matters), split into short
buckets, and measured per bucket with an FFT. Results are kept in memory for a while.
"""

from __future__ import annotations

import subprocess
import threading
from collections import OrderedDict
from pathlib import Path
from . import procs

SR = 8000
BASS_HZ = 220
FLOOR_DB = -48  # quieter than this draws as silence

_cache: OrderedDict = OrderedDict()
_lock = threading.Lock()
CACHE_ITEMS = 64


def peaks(path: Path, start: float, end: float, per_second: int = 20) -> dict:
    """{start, end, step, full: [...], bass: [...]} with values from 0 (silence) to 1."""
    import numpy as np

    start = max(0.0, start)
    end = max(start + 0.5, end)
    key = (str(path), path.stat().st_mtime if path.exists() else 0, round(start, 2), round(end, 2), per_second)
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]

    raw = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", str(path),
         "-map", "0:a:0", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
        capture_output=True, timeout=60, **procs.no_window(),
    ).stdout
    audio = np.frombuffer(raw, dtype=np.float32)
    hop = SR // per_second
    n = len(audio) // hop
    full, bass = [], []
    if n:
        frames = audio[: n * hop].reshape(n, hop).astype(np.float64)
        spec = np.abs(np.fft.rfft(frames * np.hanning(hop), axis=1)) ** 2
        freqs = np.fft.rfftfreq(hop, 1 / SR)
        low = spec[:, freqs <= BASS_HZ].sum(axis=1)
        total = spec.sum(axis=1) + 1e-20
        # Mean power per bucket (a full-scale sine is 0.5, i.e. 0 dB here); the bass gets
        # its share of that power, as measured by the FFT.
        power = (frames ** 2).mean(axis=1) * 2
        to01 = lambda e: np.clip((10 * np.log10(e + 1e-12) - FLOOR_DB) / -FLOOR_DB, 0, 1)
        full = np.round(to01(power), 3).tolist()
        bass = np.round(to01(power * low / total), 3).tolist()
    out = {"start": round(start, 3), "end": round(start + n / per_second, 3), "step": 1 / per_second,
           "full": full, "bass": bass}
    with _lock:
        _cache[key] = out
        while len(_cache) > CACHE_ITEMS:
            _cache.popitem(last=False)
    return out
