# Audio Analysis on Windows — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A Windows server measures tempo, key, mix points and "sounds like" the way a Linux one
does. Today it measures none of them, because Essentia has no Windows version.

**Architecture:**
- **A second measuring engine, `shelf/dsp.py`, in plain numpy.** It has no compiled-on-first-run
  code, which matters because every song is measured in its own helper process. Numpy is already
  in the Windows build, so nothing is added to it.
- **Which engine runs:** `analysis.py` and `sound.py` use Essentia when it's installed and `dsp`
  otherwise.
- **Same results shape:** the numbers come out exactly as today: BPM, the key name, mix points,
  and the 52-number sound fingerprint in the same order.

**Owner's decision (2026-11-10):** option 1, "a second engine for Windows; Linux and Mac keep
Essentia". The owner was offered librosa for this.
- **Ruling:** plain numpy instead of librosa. Librosa needs Numba, which compiles on first use in
  every helper process (thousands of times for a library) and can't keep its cache inside the
  frozen Windows build. Numpy adds nothing to the installer, and the methods are the same ones
  librosa uses.
- **Cost if wrong:** tempo or key slightly less accurate than librosa's. The tests pin accuracy
  on known signals.

## Global Constraints

- **Sound fingerprint layout** (52 numbers, in this order, as `sound._measure_here`):
  - 13 MFCC means, then 13 MFCC standard deviations;
  - mean and standard deviation of: spectral centroid (Hz), rolloff (Hz, 85%), flatness, flux,
    zero-crossing rate, RMS in dB;
  - 6 spectral-contrast peaks, then 6 valleys;
  - danceability;
  - onsets per second.
- **Frames:**
  - sound: 2048 samples, hop 1024, at 22050 Hz;
  - frames quieter than RMS 1e-4 are skipped;
  - a sound measurement needs at least 50 frames.
- **Tempo:** a BPM outside 30–260 is reported as none.
- **Key:** reported as `normalize_key(note, scale)`, and only when the match strength is above 0.1.
- **Fingerprints from different engines are never mixed:**
  - `sound_checked` stores the engine's version: Essentia 1, dsp 101;
  - a song is pending when `sound_checked != current`.
- **Tempo and key** use `rhythm_checked = 2` from either engine. They're interchangeable, so there
  is no re-measure.
- **Engine choice:** `procs.analysis_engine()` returns `"essentia"` when importable, otherwise
  `"dsp"`. Background measuring always runs when `analyze_tempo` is on.

## Review Focus

1. **Silence or very short files.** Expected: no crash, and none for BPM, key and fingerprint.
   *Test: `test_dsp_silence_and_short`.*
2. **Half and double tempo** (a 70 BPM track read as 140). Expected: within 2% of the true tempo
   or of an exact half or double. *Test: `test_dsp_tempo_clicks` at 90 and 128 BPM.*
3. **A Linux server whose Essentia disappears, or a server moved between engines.** Expected: its
   fingerprints are re-measured and never mixed. *Test: `test_sound_engine_switch_remeasures`.*
4. **The frozen Windows program running the helper** (`--module shelf.analysis`). Expected: it
   measures a test file. *CI step in release.yml.*
5. **Danceability and onsets on music with no clear beat.** Expected: finite numbers, never NaN.
   *Test: `test_dsp_features_shape`, with noise.*

---

### Task 1: `shelf/dsp.py` — the numpy engine

**Interfaces (Produces):**
- `tempo_and_beats(y, sr) -> (bpm: float, beats: np.ndarray seconds)`, Ellis's dynamic-programming
  beat tracker on a log-mel onset envelope.
- `key(y, sr) -> (note: str, scale: str, strength: float)`: chroma, then correlation with the
  Krumhansl–Kessler profiles over 24 keys.
- `features(y, sr=22050) -> list[float] | None`: the 52-number fingerprint.

- [ ] **Tests** (`tests/test_dsp.py`, synthetic signals):
  - `test_dsp_tempo_clicks`: clicks at 90 and 128 BPM give a tempo within 2%, with beats spaced at
    60/BPM.
  - `test_dsp_key`: sustained A–C–E tones give "A minor"; C–E–G gives "C major".
  - `test_dsp_features_shape`: 52 finite numbers for noise and for a tone. Noise has higher
    flatness than a tone.
  - `test_dsp_silence_and_short`: silence gives `features() is None` and no crash in
    `tempo_and_beats`.
- [ ] Implement, then run the tests and watch them pass. Commit.

### Task 2: Use it when Essentia is missing

- **Files:** `procs.py` (`analysis_engine()`), `analysis.py`, `sound.py` (engine dispatch and the
  version per engine), `app.py` (the gate).
- [ ] **Tests:**
  - `test_analysis_without_essentia`: with the engine forced to dsp, a generated click file gives a
    BPM, mix points and a 52-number fingerprint.
  - `test_sound_engine_switch_remeasures`.
- [ ] Implement, then run the full suite. Commit.

### Task 3: Windows release check

- [ ] In `release.yml` (server-windows), after the smoke test, run the installed
  `shelf-server.exe --module shelf.analysis` and `--module shelf.sound` on a generated click WAV,
  and fail if the BPM or the fingerprint is missing.
- [ ] Run a trial `gh workflow run release.yml`. Commit.
