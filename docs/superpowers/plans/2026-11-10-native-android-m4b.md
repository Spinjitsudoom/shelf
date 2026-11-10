# Native Android, Milestone 4b: Crossfade and Mix Transitions — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Songs can crossfade, and a playlist with Mix on hands each song to the next the way the web app does: beat-matched blends, bass swaps, filter sweeps, fades and cuts, with the playlist's per-song transitions.

**Architecture:**
- **Two ExoPlayers ("decks").** The current deck holds the queue.
- **A transition** starts the other deck on the next song at its planned in-point (at the matched tempo, pitch kept). It ramps both decks' volume, bass and filters along the web's automation curves. Then it hands over:
  - the new deck gets the rest of the queue added around its playing song, which doesn't interrupt it;
  - the old deck stops;
  - the media session switches to the new deck.
- **The planner** is a straight port of `transitions.js`.
- **Effects:** each deck's `ShelfAudioProcessor` gains the transition's bass shelf and its high-pass and low-pass filters.

**Tech Stack:** As M4a. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-09-native-android-design.md` (milestone 4: "two players, with volume and EQ curves driven by the API's mix points").

## Global Constraints

These are the web's values (`transitions.js`, `player.js`, `settings.js`):
- **Styles:** auto, blend, swap, rise, sweep, fade, cut, with the presets `PRESETS` exactly.
  - Auto picks fade if either song has no mix points or the tempos don't match. Otherwise it picks blend if the keys suit each other on the Camelot wheel, and swap if they don't.
- **Tempo:** stretched by at most 8% (`MAX_STRETCH = 0.08`), allowing half or double time. The bass cut is −26 dB. The high-pass sweeps 30→1400 Hz; the low-pass opens 350→20000 Hz.
- **Volume:** equal-power curves.
  - smooth: in 0→T, out 0→T
  - dj: in 0→T/2, out T/2→T
  - quick: in 0→T/4, out 5T/8→T
  - cut: both switch at T/2 ± 0.02 s
- **When Mix applies:** the play context has Mix on (a playlist with `mix: true`) and repeat isn't "one". Each song's `transition` is the one into the next song.
- **Crossfade setting:**
  - `crossfade` is 0..12 s (0 = off), only when Mix isn't on.
  - Within an album played in order there's no crossfade, unless `crossfadeAlbums`.
  - Length = min(setting, duration/3).
- **A skip, pause or seek mid-transition** ends it at once: the new song at full level and its own tempo.
- **After a beat-matched transition,** the incoming song eases back to its own tempo over 4 s.

## Review Focus

1. **A skip, pause or seek mid-transition.** Expected: no two songs left playing, and the right song plays at full volume. *Test: Task 3 `skipMidTransitionLeavesOneSong`.*
2. **The queue edited mid-transition** (play next, remove). Expected: the handover keeps the edit. *Test: Task 3 `handoverKeepsQueueEdits`.*
3. **Songs with no mix points, or tempos too far apart.** Expected: a plain fade timed to the outro, no tempo change. *Test: Task 1 `noMixPointsFades`.*
4. **The last song, with repeat off.** Expected: no transition (nothing to go to); autoplay's songs, once added, are mixed into. *Test: Task 3 `noTransitionWithoutNext`.*
5. **Connect, the widget and the play counter after a handover.** Expected: they follow the new deck (state reports keep coming, and the play is counted once). *Test: Task 3 `listenersFollowTheNewDeck`.*

---

### Task 1: The planner (port of transitions.js)

**Files:**
- Create `playback/Transition.kt`.
- Modify `Models`:
  - `Track` gets `bpm`, `camelot`, `mix: MixPoints?` and `transition: JsonElement?`;
  - `PlaylistDetail` gets `mix: Boolean`.
- Modify `PlayContext` (`mix: Boolean = false`).
- Test `TransitionTest`.

**Interfaces:**
- `@Serializable data class MixPoints(start, end, intro, outro, firstBeat, outBeat, outPeriod, inPeriod)`, all nullable doubles.
- `data class Plan(style, start, length, inStart, rate, beatmatch, beats, volume, eq, filter)`
- `fun tempoMatch(out, inc): Match?`
- `fun autoStyle(cur, nxt): String`
- `fun plan(cur: Track, nxt: Track, setting: JsonElement?, duration: Double): Plan`
- `fun levels(plan, side, t): Levels(gain, bassDb, highpassHz?, lowpassHz?)`
- `fun crossfadePlan(seconds: Int, albums: Boolean, shuffle: Boolean, cur, nxt, duration): Plan?`

- [ ] Tests (port the web's behaviour):
  - `tempoMatchWithinEightPercent` (also half and double time)
  - `autoPicksBlendSwapOrFade`
  - `beatmatchedPlanStartsOnABarAndEndsBeforeTheEnd`
  - `noMixPointsFades`
  - `cutHasNoOverlap`
  - `equalPowerCurves` (smooth at T/2 gives both ≈ 0.707; dj gives in = 1 at T/2)
  - `crossfadeSkipsAlbumsInOrder`
- [ ] Commit.

### Task 2: Transition effects in the audio processor

**Files:** Modify `ShelfAudioProcessor` (`setTransition(bassDb: Double, highpassHz: Double?, lowpassHz: Double?)`: a low shelf at 250 Hz, plus 12 dB/octave high-pass and low-pass biquads). Test in `ShelfAudioProcessorTest`.

- [ ] Tests:
  - `bassCutCutsBass` (100 Hz down ≥ 20 dB, 5 kHz within 1 dB)
  - `highpassThinsOut`
  - `noTransitionIsPassthrough`
- [ ] Commit.

### Task 3: Two decks

**Files:**
- Create `playback/Decks.kt`.
- Modify `PlaybackService`:
  - `player` becomes `decks.current`;
  - listeners go on both decks;
  - the session, Connect bridge, widget, play counter and queue store follow `onSwap`;
  - a 50 ms tick drives transitions.
- Modify `ConnectBridge` (takes `() -> Player`) and `Settings` (`crossfade`, `crossfadeAlbums`).
- Test `DecksTest` (Robolectric ExoPlayers; no audio output needed).

**Interfaces:** `class Decks(a: ExoPlayer, b: ExoPlayer, effects: (Player) -> ShelfAudioProcessor)` with:
- `val current: Player`
- `var onSwap: (Player) -> Unit`
- `fun tick(nowMs)`: starts, drives or finishes the transition planned for the current song.
- `fun endTransition()`: the early end, on skip, pause or seek.
- `fun planNext(): Plan?`

- [ ] Tests:
  - `handoverMovesTheQueue` (after the handover, the new deck has the whole queue, on the next song, and the old deck is empty)
  - `handoverKeepsQueueEdits`
  - `skipMidTransitionLeavesOneSong`
  - `noTransitionWithoutNext`
  - `listenersFollowTheNewDeck`
- [ ] Commit.

### Task 4: Settings and the playlist's Mix switch

**Files:**
- Modify `SettingsScreen`: Crossfade (Off, 2, 4, 6, 8, 10, 12 s) and "Crossfade songs on the same album".
- Modify `PlaylistScreen`: a Mix on/off switch for editable playlists (`PATCH /api/playlists/{id} {mix}`), with the context carrying `mix`.
- Modify `ShelfApi` (`setPlaylistMix`).
- Test `ShelfApiTest.playlistMixSwitch`.

- [ ] Tests, implement and commit.

### Task 5: Phone build

- [ ] Build preview.12, install it on the Redmi when it's connected, and record the results in `-m4b-check.md`:
  - a crossfade of 8 s between two songs
  - a Mix playlist's blend and bass swap
  - a skip mid-transition
