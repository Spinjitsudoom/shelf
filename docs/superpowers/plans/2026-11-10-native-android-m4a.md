# Native Android, Milestone 4a: Extras (Everything but Transitions) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** The native app gets the web app's extras: sleep timer, music videos, the 6-band equalizer (with balance and mono), people and Blends with friend activity, autoplay, a private session, and the remaining settings.

**Architecture:**
- **Equalizer, balance and mono:** a Media3 `AudioProcessor` in ExoPlayer's audio sink. It runs the same filters as the web app's Web Audio graph: mono, then balance, then preamp, then six peaking biquads with Q 1, then a limiter (here, a hard clamp).
- **Sleep timer:** lives in the player service, so it runs with the screen off. It fades the player's volume out over 8 s, then pauses.
- **Autoplay:** appends `/api/tracks/{id}/similar` when the last song starts, as `player.js` does.

**Tech Stack:** As M3. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-09-native-android-design.md` (milestone 4).
- Split: crossfade and Mix's beat-matched transitions need a two-player engine, so they get their own plan (M4b).

## Global Constraints

- **EQ bands (Hz):** 60, 150, 400, 1000, 2400, 15000. The presets are the web's `EQ_PRESETS`, including Metal `[4.5, 2.5, -3, -0.5, 3.5, 3]`, copied exactly.
- **Balance:** −1..1. Mono averages L and R.
- **Sleep timer choices:** 5, 15, 30, 45, 60 and 90 minutes, or "end of this song". The fade lasts 8 s.
  - Copy: "Sleep timer: N min left", "Sleep timer off", "Sleep timer: music stopped".
- **Autoplay:**
  - Only with repeat off.
  - It adds up to 25 songs not among the last 200 in the queue.
  - It does nothing when offline.
- **Private session:** Connect `state.private = true`, so friend activity leaves this phone out. Sharing listening is `PATCH /api/me {shareActivity}`.
- **Videos:** `GET /api/tracks/{id}/video` returns `{found, videoId, title, channel}`. The video opens in the YouTube app (`vnd.youtube:{id}`), falling back to `https://www.youtube.com/watch?v={id}&t={s}s`. The song pauses first.
- **People:** `GET /api/people` returns `[{id, username, canBlend}]`; `GET /api/blend/{id}` returns a mix-shaped Blend; `GET /api/activity` returns friend activity.

## Review Focus

1. **The EQ at extreme settings** (+6 dB on every band). Expected: no clipping wrap-around (samples are clamped), and Flat is bit-exact passthrough. *Test: Task 1 `flatIsPassthrough`, `boostIsClamped`.*
2. **The sleep timer with the screen off, or the app closed.** Expected: it still fades and pauses, because it lives in the service. *Test: Task 2 `fadesThenPauses`.*
3. **"End of this song" when the song is skipped.** Expected: it stops at the end of the song that's playing at the time, not the one it was set on. *Test: Task 2 `endOfSongFollowsSkips`.*
4. **Autoplay offline, or with repeat on.** Expected: nothing is added and there's no error. *Test: Task 4 `noAutoplayWithRepeatOrOffline`.*
5. **A Blend with someone who keeps their listening private** (403). Expected: it says so and doesn't crash. *Test: Task 5 `privateBlendSaysSo`.*

---

### Task 1: Equalizer, balance and mono

**Files:**
- Create `playback/ShelfAudioProcessor.kt` and `playback/Biquad.kt`, and `ui/settings/EqualizerScreen.kt`.
- Modify:
  - `Settings` (`eqEnabled`, `eqPreset`, `eqGains`, `balance`, `mono`);
  - `PlaybackService`: a `DefaultRenderersFactory` whose `buildAudioSink` adds the processor, with its parameters set from the settings;
  - `SettingsScreen` (an "Equalizer" row);
  - `AppNav` (route `settings/eq`).
- Test `ShelfAudioProcessorTest`.

**Interfaces:**
- `object Eq { val BANDS; val PRESETS: Map<String, List<Double>> }`
- `fun peaking(freq, gainDb, q, rate): Biquad`
- `fun Biquad.magnitudeDb(freq, rate): Double`
- `class ShelfAudioProcessor : BaseAudioProcessor` with `fun configure(eq: List<Double>?, balance: Float, mono: Boolean)`. `eq == null` means off. It handles 16-bit and float PCM in stereo or mono.

- [ ] Tests:
  - `peakingHitsItsGain` (+6 dB at 1 kHz measures +6 ±0.1)
  - `flatIsPassthrough`
  - `boostIsClamped`
  - `balanceLeftSilencesRight`
  - `monoAveragesChannels`
  - `presetsMatchWeb` (Metal and Flat)
- [ ] Equalizer screen:
  - an on/off switch
  - the presets in a scrolling row of chips
  - six vertical sliders (−12..+12 dB) labelled 60, 150, 400, 1k, 2.4k, 15k; moving one sets the preset to "Custom"
  - balance and mono below
- [ ] Commit.

### Task 2: Sleep timer

**Files:**
- Create `playback/SleepTimer.kt` and `ui/player/SleepSheet.kt`.
- Modify `PlaybackService` (it owns the timer and drives the fade through `player.volume` × the levelled volume) and `NowPlayingScreen` (a sleep button that shows the minutes left).
- Test `SleepTimerTest`.

**Interfaces:**
- `class SleepTimer(clock, schedule)` with:
  - `val state: StateFlow<SleepState?>` (`SleepState(endsAt: Long?, endOfSong: Boolean)`)
  - `fun set(minutes: Int)`, `fun endOfSong()`, `fun cancel()`
  - `fun onTick(): Float`, the fade multiplier (1 → 0 over the last 8 s; at 0 it calls `onStop`)
  - `fun onSongEnded()` (stops if end-of-song is set)
- The UI reaches it through `container.sleep`, the one the service drives.

- [ ] Tests:
  - `fadesThenPauses`
  - `endOfSongFollowsSkips` (a skip doesn't stop; the end of whatever plays does)
  - `cancelRestoresVolume`
- [ ] Commit.

### Task 3: Music videos

**Files:**
- Modify `ShelfApi.video(id)`, `Models` (`VideoInfo`) and `NowPlayingScreen`: a video button when one is found, which pauses the song and opens the YouTube app.
- Test `ShelfApiTest.videoParses` and `VideoLinkTest`.

**Interfaces:** `fun youtubeIntents(videoId: String, atSeconds: Int): List<Intent>`, app first, then the web.

- [ ] Tests: `videoParses`, `appThenWebLinks`. Commit.

### Task 4: Autoplay, private session, and the remaining settings

**Files:**
- Modify `Settings`:
  - `autoplay = true`
  - `privateSession = false`
  - `spinDisc = true`
  - `deviceName = ""`
  - `downloadQuality = "veryhigh"`
- Modify:
  - `PlaybackService` (autoplay when the last song starts);
  - `ConnectBridge` (`private` in the state);
  - `ConnectClient` (`rename` when the device name changes);
  - `Disc` (no spinning when `spinDisc` is off);
  - `Downloads` (uses `downloadQuality`);
  - `SettingsScreen`, with the new rows: Autoplay; Private session; Share what I play (PATCH /api/me); Spin the disc; Device name; Download quality.
- Tests: `AutoplayTest`, `ConnectBridgeTest.privateSessionIsReported`.

**Interfaces:** `fun autoplayPick(queueIds: List<Int>, similar: List<Track>, repeatOff: Boolean): List<Track>`.

- [ ] Tests:
  - `addsFreshSimilarSongs` (it skips the last 200 ids, caps at 25)
  - `noAutoplayWithRepeatOrOffline`
  - `privateSessionIsReported`
- [ ] Commit.

### Task 5: People, Blends and friend activity

**Files:**
- Modify `ShelfApi` (`people`, `blend(id)` as a `MixDetail`, `activity`) and `Models` (`Person`, `Activity`).
- Create `ui/browse/PeopleScreen.kt`: friend activity (who's playing what now, or last, with the device), then Blend with each person.
- Modify `AppNav` (routes `people` and `blend/{id}`, the latter reusing MixScreen's layout with a tape cover) and `HomeScreen` (a people button in the header).
- Test `ShelfApiTest.peopleAndBlend`, `privateBlendSaysSo`.

- [ ] Tests, implement and commit.

### Task 6: Phone build

- [ ] Build preview.11 (`-Ppreview`), install it on the Redmi when it's connected, and write `-m4a-check.md` after the owner's check.
