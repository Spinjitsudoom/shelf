"""Listening to songs with plain numpy: tempo and beats, key, and the "sounds like" fingerprint.

This is the engine for servers without Essentia (it has no Windows version). The methods are
the standard ones, as librosa implements them:

- Tempo: an onset-strength envelope (how much the log-mel spectrum rises from one frame to the
  next), its autocorrelation weighted towards 120 BPM, then Ellis's dynamic-programming beat
  tracker to place the beats.
- Key: a chroma profile (how much of each of the 12 notes there is), correlated with the
  Krumhansl–Kessler major and minor key profiles in all 24 keys.
- The fingerprint: the same 52 numbers, in the same order, as the Essentia one in sound.py
  (MFCCs, brightness, noisiness, spectral contrast, level, danceability, busyness), so the rest
  of Shelf treats both alike. The two engines' numbers aren't comparable with each other, though,
  so a library is never measured with a mix of them (see sound.py).

Everything works on mono float32 audio at 22050 Hz, and in blocks, so a long song doesn't need
a big spectrogram in memory.
"""

from __future__ import annotations

import numpy as np

NOTES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

N_FFT, HOP = 2048, 512  # tempo and key
F_FFT, F_HOP = 2048, 1024  # fingerprint


def _spectra(y: np.ndarray, n_fft: int, hop: int, block: int = 512):
    """Magnitude spectra of hann-windowed frames, `block` frames at a time: (frames, bins)."""
    if len(y) < n_fft:
        y = np.pad(y, (0, n_fft - len(y)))
    count = 1 + (len(y) - n_fft) // hop
    window = np.hanning(n_fft).astype(np.float32)
    view = np.lib.stride_tricks.sliding_window_view(y, n_fft)[::hop][:count]
    for i in range(0, count, block):
        yield np.abs(np.fft.rfft(view[i:i + block] * window, axis=1)).astype(np.float32)


def _mel_filters(sr: int, n_fft: int, n_mels: int, fmin: float = 0.0, fmax: float | None = None) -> np.ndarray:
    """Triangular mel filters, (n_mels, bins), each with unit area (Slaney style)."""
    fmax = fmax or sr / 2
    mel = lambda f: 2595 * np.log10(1 + f / 700)
    hz = lambda m: 700 * (10 ** (m / 2595) - 1)
    edges = hz(np.linspace(mel(fmin), mel(fmax), n_mels + 2))
    freqs = np.fft.rfftfreq(n_fft, 1 / sr)
    out = np.zeros((n_mels, len(freqs)), dtype=np.float32)
    for m in range(n_mels):
        lo, mid, hi = edges[m], edges[m + 1], edges[m + 2]
        up = (freqs - lo) / (mid - lo)
        down = (hi - freqs) / (hi - mid)
        out[m] = np.maximum(0, np.minimum(up, down)) * (2 / (hi - lo))
    return out


# ---------------------------------------------------------------- tempo and beats

def onset_envelope(y: np.ndarray, sr: int) -> np.ndarray:
    """How sharply the sound rises in each frame (hop 512): the mean positive change of the
    log-mel spectrum. Zero for silence."""
    mel = _mel_filters(sr, N_FFT, 40)
    rows = [np.log10(mel @ (s.T ** 2) + 1e-10) * 10 for s in _spectra(y, N_FFT, HOP)]
    if not rows:
        return np.zeros(0, dtype=np.float32)
    db = np.concatenate(rows, axis=1)
    db = np.maximum(db, db.max() - 80)  # the quietest parts say nothing
    rise = np.maximum(0, np.diff(db, axis=1)).mean(axis=0)
    env = np.concatenate([[0.0], rise])
    env -= np.convolve(env, np.ones(16) / 16, mode="same") * 0.5  # take out slow swells
    return np.maximum(env, 0).astype(np.float32)


def _tempo_from_envelope(env: np.ndarray, fps: float, start_bpm: float = 120.0) -> float:
    """The tempo whose beat period best repeats in the envelope, favouring ~120 BPM (one
    octave of spread either way), refined between frames."""
    if len(env) < 8 or not env.any():
        return 0.0
    e = env - env.mean()
    n = len(e)
    spec = np.fft.rfft(e, 2 * n)
    ac = np.fft.irfft(spec * np.conj(spec))[:n]
    lo, hi = int(fps * 60 / 260), min(n - 2, int(fps * 60 / 30))
    if hi <= lo + 2:
        return 0.0
    lags = np.arange(lo, hi + 1)
    bpms = 60 * fps / lags
    prior = np.exp(-0.5 * (np.log2(bpms / start_bpm) / 1.0) ** 2)
    score = ac[lo:hi + 1] / (ac[0] + 1e-9) * prior
    i = int(np.argmax(score))
    lag = float(lags[i])
    if 0 < i < len(score) - 1:  # a parabola through the peak and its neighbours
        a, b, c = ac[lags[i] - 1], ac[lags[i]], ac[lags[i] + 1]
        d = a - 2 * b + c
        if d < 0:
            lag += 0.5 * (a - c) / d
    return 60 * fps / lag


def _track_beats(env: np.ndarray, period: float, tightness: float = 100.0) -> np.ndarray:
    """Ellis's beat tracker: the chain of beats about `period` frames apart that lands on the
    strongest onsets. Returns frame indices."""
    n = len(env)
    norm = env / (env.std() + 1e-9)
    width = max(1, int(round(period / 32)))
    g = np.exp(-0.5 * (np.arange(-width * 4, width * 4 + 1) / width) ** 2)
    local = np.convolve(norm, g, mode="same")
    score = np.zeros(n)
    back = -np.ones(n, dtype=int)
    lo, hi = int(round(period / 2)), int(round(2 * period))
    offsets = np.arange(lo, hi + 1)
    penalty = -tightness * np.log(offsets / period) ** 2
    for t in range(n):
        prev = t - offsets
        ok = prev >= 0
        if ok.any():
            cand = score[prev[ok]] + penalty[ok]
            j = int(np.argmax(cand))
            if cand[j] > 0:
                score[t] = local[t] + cand[j]
                back[t] = prev[ok][j]
                continue
        score[t] = local[t]
    # The last beat: the best-scoring frame in the final beat period that's a real onset.
    tail = np.arange(max(0, n - hi), n)
    last = int(tail[np.argmax(score[tail])]) if len(tail) else n - 1
    beats = []
    while last >= 0:
        beats.append(last)
        last = back[last]
    beats = np.array(beats[::-1])
    # Trim the weak beats at either end (fades, silence).
    if len(beats):
        strong = local[beats] > 0.5 * np.sqrt((local[beats] ** 2).mean())
        keep = np.nonzero(strong)[0]
        beats = beats[keep[0]:keep[-1] + 1] if len(keep) else beats[:0]
    return beats


def tempo_and_beats(y: np.ndarray, sr: int) -> tuple[float, np.ndarray]:
    """(BPM, beat times in seconds). (0, []) for silence or something too short."""
    env = onset_envelope(np.asarray(y, dtype=np.float32), sr)
    fps = sr / HOP
    bpm = _tempo_from_envelope(env, fps)
    if not bpm:
        return 0.0, np.zeros(0)
    beats = _track_beats(env, 60 * fps / bpm)
    times = beats * HOP / sr
    if len(times) >= 8:  # the beats themselves give the steadiest tempo
        bpm = 60 / float(np.median(np.diff(times)))
    return float(bpm), times


# ---------------------------------------------------------------- key

def chroma(y: np.ndarray, sr: int) -> np.ndarray:
    """How much of each note (C, C♯ ... B) there is over the whole song, from 100 Hz to 5 kHz
    (below that, bass and kick drum blur the key: on real songs this range agreed with
    Essentia's key far more often than one starting at 55 Hz)."""
    freqs = np.fft.rfftfreq(N_FFT, 1 / sr)
    use = (freqs >= 100) & (freqs <= 5000)
    pc = (np.round(69 + 12 * np.log2(freqs[use] / 440)).astype(int)) % 12
    total = np.zeros(12)
    for s in _spectra(y, N_FFT, HOP):
        power = (s[:, use] ** 2).sum(axis=0)
        total += np.bincount(pc, weights=power, minlength=12)
    return total


def key(y: np.ndarray, sr: int) -> tuple[str, str, float]:
    """(note, "major"/"minor", strength 0..1): the key profile the notes match best."""
    c = chroma(np.asarray(y, dtype=np.float32), sr)
    if not c.any():
        return "C", "major", 0.0
    c = c / c.max()
    best = ("C", "major", -1.0)
    for tonic in range(12):
        for scale, profile in (("major", _MAJOR), ("minor", _MINOR)):
            r = float(np.corrcoef(c, np.roll(profile, tonic))[0, 1])
            if r > best[2]:
                best = (NOTES[tonic], scale, r)
    return best[0], best[1], max(0.0, best[2])


# ---------------------------------------------------------------- the fingerprint

def _dct_matrix(n_in: int, n_out: int) -> np.ndarray:
    k = np.arange(n_out)[:, None]
    i = np.arange(n_in)[None, :]
    m = np.cos(np.pi / n_in * (i + 0.5) * k) * np.sqrt(2 / n_in)
    m[0] /= np.sqrt(2)
    return m


def _contrast_edges(sr: int, bands: int = 6, lo: float = 20.0, hi: float = 11000.0) -> np.ndarray:
    freqs = np.fft.rfftfreq(F_FFT, 1 / sr)
    edges = np.geomspace(lo, min(hi, sr / 2), bands + 1)
    return np.searchsorted(freqs, edges)


def features(y: np.ndarray, sr: int = 22050) -> list[float] | None:
    """The 52-number fingerprint (layout as sound.py's Essentia one), or None when there's
    too little sound to say."""
    y = np.asarray(y, dtype=np.float32)
    if len(y) < F_FFT:
        return None
    freqs = np.fft.rfftfreq(F_FFT, 1 / sr)
    mel = _mel_filters(sr, F_FFT, 40)
    dct = _dct_matrix(40, 13)
    edges = _contrast_edges(sr)
    frames = np.lib.stride_tricks.sliding_window_view(y, F_FFT)[::F_HOP]
    rms_all = np.sqrt((frames.astype(np.float64) ** 2).mean(axis=1))
    keep = rms_all >= 1e-4  # silence says nothing about how it sounds
    if keep.sum() < 50:
        return None
    frames, rms = frames[keep], rms_all[keep]
    mags = np.concatenate(list(_spectra_frames(frames)))

    mfcc = (dct @ (10 * np.log10(mel @ (mags.T ** 2) + 1e-10))).T
    total = mags.sum(axis=1) + 1e-12
    centroid = (mags * freqs).sum(axis=1) / total
    cum = np.cumsum(mags ** 2, axis=1)
    rolloff = freqs[np.argmax(cum >= 0.85 * cum[:, -1:], axis=1)]
    flatness = np.exp(np.log(mags + 1e-12).mean(axis=1)) / (mags.mean(axis=1) + 1e-12)
    flux = np.concatenate([[0.0], np.sqrt((np.diff(mags, axis=0) ** 2).sum(axis=1))])
    signs = np.signbit(frames)
    zcr = (signs[:, 1:] != signs[:, :-1]).mean(axis=1)
    level = 20 * np.log10(rms + 1e-9)
    peaks, valleys = [], []
    for b in range(len(edges) - 1):
        band = np.sort(mags[:, edges[b]:max(edges[b + 1], edges[b] + 1)], axis=1)
        k = max(1, int(round(band.shape[1] * 0.4)))
        valley = np.log(band[:, :k].mean(axis=1) + 1e-9)
        peak = np.log(band[:, -k:].mean(axis=1) + 1e-9)
        peaks.append(peak - valley)
        valleys.append(valley)

    vec = list(mfcc.mean(axis=0)) + list(mfcc.std(axis=0))
    for a in (centroid, rolloff, flatness, flux, zcr, level):
        vec += [float(a.mean()), float(a.std())]
    vec += [float(np.mean(p)) for p in peaks] + [float(np.mean(v)) for v in valleys]
    vec += [danceability(y, sr), onset_rate(y, sr)]
    return [round(float(x), 5) if np.isfinite(x) else 0.0 for x in vec]


def _spectra_frames(frames: np.ndarray, block: int = 512):
    window = np.hanning(F_FFT).astype(np.float32)
    for i in range(0, len(frames), block):
        yield np.abs(np.fft.rfft(frames[i:i + block] * window, axis=1)).astype(np.float32)


def danceability(y: np.ndarray, sr: int) -> float:
    """How steady and strong the pulse is, 0..1: the clearest repetition of the onset envelope
    at a danceable tempo (60–180 BPM)."""
    env = onset_envelope(y, sr)
    if len(env) < 16 or not env.any():
        return 0.0
    e = env - env.mean()
    spec = np.fft.rfft(e, 2 * len(e))
    ac = np.fft.irfft(spec * np.conj(spec))[:len(e)]
    fps = sr / HOP
    lo, hi = int(fps * 60 / 180), min(len(ac) - 1, int(fps * 60 / 60))
    if hi <= lo:
        return 0.0
    return float(max(0.0, ac[lo:hi + 1].max() / (ac[0] + 1e-9)))


def onset_rate(y: np.ndarray, sr: int) -> float:
    """Onsets per second: peaks in the onset envelope that stand out from their surroundings."""
    env = onset_envelope(y, sr)
    if len(env) < 8 or not env.any():
        return 0.0
    fps = sr / HOP
    thresh = np.convolve(env, np.ones(32) / 32, mode="same") + 0.5 * env.std()
    w = 3
    padded = np.pad(env, w, constant_values=-np.inf)
    window = np.lib.stride_tricks.sliding_window_view(padded, 2 * w + 1)
    peaks = (env == window.max(axis=1)) & (env > thresh)
    return float(peaks.sum() / (len(env) / fps))
