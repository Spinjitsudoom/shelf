"""The numpy measuring engine (used where Essentia isn't available, i.e. Windows)."""

import numpy as np
import pytest

from shelf import dsp

SR = 22050


def clicks(bpm: float, seconds: float = 30, sr: int = SR) -> np.ndarray:
    """A click track: a short decaying burst of noise on every beat, with a quieter tick between."""
    y = np.zeros(int(seconds * sr), dtype=np.float32)
    rng = np.random.default_rng(1)
    burst = rng.standard_normal(int(0.03 * sr)).astype(np.float32) * np.exp(-np.linspace(0, 8, int(0.03 * sr)))
    period = 60 / bpm
    t = 0.5
    while t < seconds - 0.1:
        i = int(t * sr)
        y[i:i + len(burst)] += burst
        j = int((t + period / 2) * sr)
        y[j:j + len(burst)] += 0.15 * burst[: len(y[j:j + len(burst)])]
        t += period
    return y


def tones(freqs, seconds: float = 20, sr: int = SR) -> np.ndarray:
    t = np.arange(int(seconds * sr)) / sr
    y = sum(np.sin(2 * np.pi * f * t) + 0.4 * np.sin(4 * np.pi * f * t) for f in freqs)
    return (0.2 * y).astype(np.float32)


@pytest.mark.parametrize("bpm", [90, 128])
def test_dsp_tempo_clicks(bpm):
    found, beats = dsp.tempo_and_beats(clicks(bpm), SR)
    assert abs(found - bpm) / bpm < 0.02, found
    gaps = np.diff(beats)
    assert abs(np.median(gaps) - 60 / bpm) < 0.02


def test_dsp_key():
    a, c, e, g = 220.0, 261.63, 329.63, 392.0
    note, scale, strength = dsp.key(tones([a, c, e]), SR)
    assert (note, scale) == ("A", "minor") and strength > 0.1
    note, scale, _ = dsp.key(tones([c, e, g]), SR)
    assert (note, scale) == ("C", "major")


def test_dsp_features_shape():
    rng = np.random.default_rng(2)
    noise = (0.1 * rng.standard_normal(SR * 20)).astype(np.float32)
    tone = tones([440.0])
    fn, ft = dsp.features(noise, SR), dsp.features(tone, SR)
    assert len(fn) == len(ft) == 52
    assert all(np.isfinite(fn)) and all(np.isfinite(ft))
    flatness_mean = 26 + 2 * 2  # after the MFCCs: centroid, rolloff, then flatness (mean, std)
    assert fn[flatness_mean] > ft[flatness_mean]


def test_dsp_silence_and_short():
    silence = np.zeros(SR * 20, dtype=np.float32)
    assert dsp.features(silence, SR) is None
    bpm, beats = dsp.tempo_and_beats(silence, SR)
    assert bpm == 0 and len(beats) == 0
    assert dsp.key(silence, SR)[2] == 0
