# Native Android, Milestone 1: Foundation and Playing Music — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A native Shelf Preview app (installed beside today's WebView app) that signs in to a Shelf server, browses Home, Library, albums, artists, playlists and mixes, and plays music through a Media3 background service with notification, lock screen, mini player, Now Playing, queue and swipe-to-skip.

**Architecture:** Single-activity Kotlin app, Jetpack Compose UI with Shelf's own theme, Navigation Compose. A small `AppContainer` owns the `ShelfApi` (OkHttp + kotlinx.serialization, Bearer token) and `ServerStore`. Playback lives in `PlaybackService` (Media3 `MediaLibraryService` + ExoPlayer streaming `/api/tracks/{id}/stream`), and the UI talks to it only through a `MediaController` wrapped in `PlayerConnection`.

**Tech Stack:** Kotlin 2.4.21, AGP 9.4.1, Gradle 9.8.1, Compose BOM 2026.09.00, Media3 1.11.1, Navigation Compose 2.10.2, activity-compose 1.13.0, lifecycle 2.11.0, OkHttp 5.5.1 (+ mockwebserver3), kotlinx-serialization-json 1.12.0, kotlinx-coroutines 1.11.0, Coil 3.6.3, core-ktx 1.19.1, JUnit 4.

**Spec:** `docs/superpowers/specs/2026-11-09-native-android-design.md`

## Global Constraints

- Package `app.shelf`, **applicationId `app.shelf.preview`**, launcher label **"Shelf Preview"** until the M3 switch-over. Must install beside the existing `app.shelf`.
- minSdk 26, compileSdk 36, targetSdk 36; edge-to-edge.
- All versions exactly as in the Tech Stack line (pinned in `android/gradle/libs.versions.toml`); no other dependencies without a reason in the commit message.
- Signed with the existing key: keystore `~/.local/share/android-build/debug.keystore`, alias `shelf`, store and key password `android`. In CI the keystore comes from the `ANDROID_KEYSTORE_BASE64` secret. versionCode = `major*10000 + minor*100 + patch`.
- Cleartext http must work (home servers are plain http on the LAN): `android:usesCleartextTraffic="true"`.
- Auth: `POST /api/login {username,password}` returns `{token,user}`; every request sends `Authorization: Bearer <token>`. That includes ExoPlayer's stream requests and Coil's cover requests.
- URLs: covers `api/albums/{albumId}/cover?size={px}&v={coverVersion}` (no cover if `cover` is null); stream `api/tracks/{id}/stream?q={original|veryhigh|high|normal|low}`.
- A play is recorded with `POST /api/tracks/{id}/played` once heard time ≥ `min(240 s, duration/2)` (seeking doesn't count), at most once per time a track starts.
- Look: Shelf's palette. Dark: tray `#1a1d24`, sleeve `#232731`, ink `#e6e9ef`, ink-2 `#99a1b0`, rule `#323745`, cobalt `#8199ff`, cobalt-ink `#0f1424`. Light: tray `#e9ebee`, sleeve `#f7f8fa`, ink `#1c2029`, ink-2 `#5a6271`, rule `#d3d7de`, cobalt `#2c4fd0`, cobalt-ink `#ffffff`. Fonts: Archivo (UI) and Caveat (tape labels), both OFL. Dark is the default.
- Branding: no Spotify green, no copies of Spotify's icons or the Liked Songs gradient, use the names "Favourites" and "Shelf Mix".
- Copy is plain sentence case and says what happened and what to do, e.g. "Couldn’t reach 192.168.1.20:4533. Check the server is running and this phone is on the same network."

## Review Focus

1. **The server is unreachable** at launch or mid-browse. Expected: every screen shows its error state with "Try again", nothing crashes, and music already playing carries on. *Test in Task 3 (`networkFailureIsOffline`) and Task 5 (`errorStateRetries`).*
2. **The token is revoked** (password changed or signed out elsewhere, so 401). Expected: back to sign-in with the server address kept, not a blank screen. *Test in Task 3 (`unauthorizedIsSignedOut`) and Task 4 (`expiredTokenGoesToSignIn`).*
3. **The process is killed** (MIUI, low memory) while paused, then reopened. Expected: the same queue, song and position, paused. *Test in Task 6 (`queueStoreRoundTrip`, `restoresPausedAtSavedPosition`).*
4. **Albums with no cover or colour, and very long or non-Latin titles** (Måneskin, 日本語, 200 characters). Expected: a fallback colour and placeholder, single-line ellipsis, no layout break. *Test in Task 2 (`fallbackColorMatchesWeb`, `coverWithoutArtShowsTitle`) and Task 7 (`longTitleStaysOneLine`).*
5. **Swiping at the ends of the queue,** or a swipe that's too short. Expected: it springs back with no skip. *Test in Task 7 (`swipeAtQueueEndSpringsBack`, `shortSwipeDoesNothing`).*

---

### Task 1: Project skeleton, toolchain and CI (legacy app moved aside)

**Files:**
- Move: `android/` → `android-legacy/` (`git mv`; `build.sh` uses paths relative to itself, so it keeps working)
- Modify: `.github/workflows/release.yml` (job `android`: `bash android-legacy/build.sh`, `cp android-legacy/build/shelf.apk …`), `README.md` (references to `android/build.sh`), `.gitignore` (`android-legacy/build/`, `android/.gradle/`, `android/**/build/`, `android/local.properties`)
- Create: `android/settings.gradle.kts`, `android/build.gradle.kts`, `android/gradle.properties`, `android/gradle/libs.versions.toml`, the Gradle wrapper (`gradlew`, `gradlew.bat`, `gradle/wrapper/*`), `android/app/build.gradle.kts`, `android/app/src/main/AndroidManifest.xml`, `android/app/src/main/java/app/shelf/MainActivity.kt`, `android/app/src/test/java/app/shelf/SmokeTest.kt`
- Modify: `.github/workflows/tests.yml` (new job **"Android app (native)"**: temurin 17, `cd android && ./gradlew --no-daemon testDebugUnitTest assembleRelease`)

**Interfaces:**
- Produces: a buildable module `:app`. `./gradlew assembleRelease -PversionName=X -PversionCode=N` sets those (defaults `0.7.0` and `700`). Signing reads env `SHELF_KEYSTORE` (path), falling back to `~/.local/share/android-build/debug.keystore`.

- [ ] **Step 1:** Install SDK parts locally: `~/.local/share/android-build/sdk/cmdline-tools/latest/bin/sdkmanager "platforms;android-36" "build-tools;36.0.0"` (accept licences). Write `android/local.properties` with `sdk.dir=…` (git-ignored).
- [ ] **Step 2:** Generate the wrapper with Gradle 9.8.1 (download the distribution into the scratchpad and run `gradle wrapper --gradle-version 9.8.1` in `android/`). Because the NAS share can't hold symlinks, build from a scratchpad copy if Gradle fails on CIFS. Note which way works in the commit message.
- [ ] **Step 3:** Write `SmokeTest.kt` (`fun appIdIsPreview()`, asserting `BuildConfig.APPLICATION_ID == "app.shelf.preview"`) and a `MainActivity` showing "Shelf Preview" in Compose with `enableEdgeToEdge()`.
- [ ] **Step 4:** Run `./gradlew testDebugUnitTest assembleRelease`. Expected: the test passes and `app/build/outputs/apk/release/app-release.apk` exists, signed. Check with `apksigner verify --print-certs` that the SHA-256 is `3a87443d…6b96000` (the same key as `app.shelf`).
- [ ] **Step 5:** Install on the Redmi (`adb -s d44407270407 install -r …`). Expected: two launcher icons, "Shelf" and "Shelf Preview", and the old app still works. Check `bash android-legacy/build.sh` still builds.
- [ ] **Step 6:** Commit and push: "Android: native app skeleton (Shelf Preview); WebView app moved to android-legacy". Confirm the new CI job passes.

### Task 2: Theme and the cover components

**Files:**
- Create: `ui/theme/Color.kt`, `ui/theme/Type.kt`, `ui/theme/Theme.kt`, `ui/covers/AlbumColors.kt`, `ui/covers/CaseCover.kt`, `ui/covers/TapeCover.kt`, `res/font/archivo.ttf`, `res/font/caveat.ttf` (from `github.com/google/fonts` `ofl/archivo/Archivo[wdth,wght].ttf` and `ofl/caveat/Caveat[wght].ttf`), `res/raw/fonts_ofl.txt`
- Test: `src/test/.../AlbumColorsTest.kt`, `src/androidTest/.../CoversTest.kt`

**Interfaces:**
- Produces:
  - `@Composable fun ShelfTheme(dark: Boolean = true, content: @Composable () -> Unit)` and `object ShelfColors` (the tokens above).
  - `fun albumColor(hex: String?, title: String): Color`: parses `#rrggbb`; otherwise falls back to `fallbackColor(title)`.
  - `fun fallbackColor(text: String): Color`: an exact port of `src/shelf/web/js/util.js:83` (31-hash over code points, unsigned 32-bit, `hsl(h%360, 28%, 42%)`).
  - `@Composable fun CaseCover(url: String?, title: String, color: Color, modifier: Modifier, vinyl: Boolean = false)`: a jewel case with the clear hinge spine on the left, as the web `.case` styling does. `vinyl` shows a sleeve with the record peeking out.
  - `@Composable fun TapeCover(name: String, color: Color, covers: List<String>, modifier: Modifier)`: the mix tape (the card insert with up to 4 covers along the top, and the cassette askew at -3.5° with a Caveat label). It's a port of `mixCover`/`TAPE_SHELL` in `views.js` and `.mix-tape` in `style.css`, drawn with Compose Canvas.

- [ ] **Step 1:** Write `fallbackColorMatchesWeb` (the expected colours are `Shelf` → `hsl(...)` and `Måneskin` → `hsl(...)`; compute the expected values by running the JS function in Node and paste them in) and `albumColorParsesHex`, which also checks that `null` and `"red"` fall back.
- [ ] **Step 2:** Run `./gradlew testDebugUnitTest --tests '*AlbumColorsTest*'`. Expected: FAIL (not defined).
- [ ] **Step 3:** Implement `Color.kt`, `AlbumColors.kt`, `Type.kt` (Archivo for everything, display styles at width 125 and weight 900 like `.album-title`) and `Theme.kt`.
- [ ] **Step 4:** Run it. Expected: PASS.
- [ ] **Step 5:** Write the instrumented test `coverWithoutArtShowsTitle` (`CaseCover(url = null, title = "Abbey Road", …)` shows the text "Abbey Road") and `tapeShowsName` (`TapeCover("Shelf Mix 1", …)` has the text "Shelf Mix 1"). Implement both covers. Run `./gradlew connectedDebugAndroidTest` with the Redmi attached. Expected: PASS.
- [ ] **Step 6:** Add a debug-only `@Preview` gallery screen. Screenshot it on the Redmi (`adb exec-out screencap`), compare it with the web app's album and tape covers, and fix anything that looks off.
- [ ] **Step 7:** Commit: "Android native: Shelf theme, fonts, jewel case and mix tape covers".

### Task 3: API client and server storage

**Files:**
- Create: `data/Models.kt`, `data/ShelfApi.kt`, `data/ServerStore.kt`, `data/ShelfError.kt`, `AppContainer.kt`, `ShelfApp.kt` (an `Application` subclass that holds `AppContainer`)
- Test: `src/test/.../ShelfApiTest.kt`, `src/test/resources/fixtures/*.json`

**Interfaces:**
- Produces (in `app.shelf.data`):
  - `@Serializable` models, all with `ignoreUnknownKeys`:
    - `User(id: Int, username: String, admin: Boolean)`
    - `Session(setup: Boolean, signedIn: Boolean, user: User?, version: String)`
    - `Album(id, title, artist, artists: List<String> = emptyList(), year: Int?, genre: String?, trackCount: Int, duration: Double, color: String?, cover: String?)`
    - `Track(id, title, artist, artists: List<String> = emptyList(), album: String, albumId: Int, albumArtist: String?, cover: String?, trackNo: Int?, discNo: Int?, duration: Double, codec: String?, bits: Int?, sampleRate: Int?, lufs: Double?, peak: Double?)`
    - `AlbumDetail(album fields + tracks: List<Track>)`
    - `ArtistPage(name, albums: List<Album>, popular: List<Track>, appearsOn: List<Album>)`
    - `PlaylistSummary(id, name, description: String?, trackCount, duration, covers: List<CoverRef>, canEdit: Boolean)`
    - `PlaylistDetail(summary fields + tracks)`
    - `CoverRef(albumId: Int, cover: String?)`
    - `MixSummary(key, name, description, color, kind, covers: List<CoverRef>)`
    - `MixDetail(MixSummary fields + tracks)`
    - `Home(recent: List<Album>, added: List<Album>, rediscover: List<Album>)`
  - `sealed class ShelfError : Exception { Offline; SignedOut; NotShelf; Server(code: Int, message: String) }`
  - `class ShelfApi(base: HttpUrl, tokenProvider: () -> String?, client: OkHttpClient)` with suspend functions:
    - `ping(): String` (the version; throws `NotShelf` if `app != "shelf"`)
    - `session()`
    - `login(username, password): Pair<String, User>`
    - `home()`, `albums(sort: String = "recent")`, `album(id)`, `artists()`, `artist(name)`
    - `playlists()`, `playlist(id)`, `likes(): List<Track>`
    - `mixes()`, `mix(key)`, `played(trackId)`
    - `coverUrl(albumId: Int, version: String?, size: Int): String?`
    - `streamUrl(trackId: Int, quality: String): String`
  - `fun normalizeServer(input: String): String?`: the same rules as `normalizeServer` in `src/shelf/web/js/server.js`.
  - `class ServerStore(prefs: SharedPreferences)` with `server: String?`, `token: String?`, `username: String?` and `fun signOut()` (clears the token, keeps the server).
  - `class AppContainer(context)` with `store`, `api` (rebuilt when the server changes), `okHttp` (adds `Authorization: Bearer` to requests for the chosen server's host only).

- [ ] **Step 1:** Capture fixtures from the preview server (port 4544, user `Etienne`/`secret-pass`): `session.json`, `home.json`, `album.json`, `artist.json`, `playlists.json`, `mixes.json`, `mix.json`, `likes.json`.
- [ ] **Step 2:** Write the tests using `MockWebServer`:
  - `pingRejectsNonShelf` and `pingReturnsVersion`
  - `loginSendsJsonAndStoresToken`
  - `requestsCarryBearerToken`
  - `unauthorizedIsSignedOut` (401 → `ShelfError.SignedOut`)
  - `networkFailureIsOffline` (server shut down → `ShelfError.Offline`)
  - `parsesFixtures` (each fixture decodes; `album.tracks` is non-empty; unknown fields are ignored)
  - `coverUrlNullWithoutVersion`
  - `streamUrlCarriesQuality`
  - `normalizeServerCases`: `"192.168.1.20:4533"` → `"http://192.168.1.20:4533"`, `"https://x.ts.net/"` → `"https://x.ts.net"`, `"ftp://x"` → null, `""` → null
- [ ] **Step 3:** Run them. Expected: FAIL.
- [ ] **Step 4:** Implement. 401 means `SignedOut`. An `IOException` means `Offline`. Any other non-2xx means `Server(code, detail)`, using `detail` from the JSON body, which FastAPI sends.
- [ ] **Step 5:** Run them. Expected: all pass.
- [ ] **Step 6:** Commit: "Android native: API client, models and server storage".

### Task 4: Server address, sign-in and app navigation

**Files:**
- Create: `ui/start/ServerScreen.kt`, `ui/start/SignInScreen.kt`, `ui/start/StartViewModel.kt`, `ui/AppNav.kt` (NavHost and the bottom bar with Home and Library)
- Modify: `MainActivity.kt`
- Test: `src/test/.../StartViewModelTest.kt`

**Interfaces:**
- Consumes: `ShelfApi`, `ServerStore`, `normalizeServer` (Task 3).
- Produces: routes `server`, `signIn`, `home`, `library`, `album/{id}`, `artist/{name}`, `playlist/{id}`, `mix/{key}`, `favourites`. `AppNav(container, miniPlayer: @Composable () -> Unit = {})`: a slot above the bottom bar, filled by Task 7. `fun interface SignedOutHandler { fun signedOut() }`: any screen that catches `ShelfError.SignedOut` calls it, and `AppNav` then goes to `signIn`.

- [ ] **Step 1:** Write the ViewModel tests:
  - `badAddressShowsHint` (`"ftp://x"` gives "That doesn’t look like a server address. Try something like 192.168.1.20:4533.")
  - `unreachableServerMessage` (Offline gives "Couldn’t reach {host}. Check the server is running and this phone is on the same network.")
  - `notShelfMessage`
  - `setupNeededMessage` (`session.setup == true` gives "This server has no accounts yet. Open it in a browser to create the admin account.")
  - `wrongPasswordMessage` (401 at login gives "Wrong username or password.")
  - `lockedOutMessage` (429 shows the server's `detail`)
  - `expiredTokenGoesToSignIn` (a stored token, then `session()` says `signedIn=false`, gives the `signIn` destination with the server kept)
- [ ] **Step 2:** Run them. Expected: FAIL. **Step 3:** Implement the ViewModel and both screens. The address field uses the URL keyboard; IME Next/Done submit; there's a progress state while checking; the last-used address is prefilled. **Step 4:** Run them. Expected: PASS.
- [ ] **Step 5:** On the Redmi, enter the LAN address and sign in as Etienne Axiak. Expected: you land on an empty Home placeholder. Kill the app and reopen it. Expected: straight to Home.
- [ ] **Step 6:** Commit: "Android native: server address, sign-in, navigation".

### Task 5: Browse screens

**Files:**
- Create: `ui/common/LoadState.kt` (`sealed interface Load<out T> { Loading; Ready(value); Failed(error: ShelfError) }` and `@Composable fun <T> LoadContent(state, onRetry, content)` with skeletons, the error copy and "Try again"), `ui/home/HomeScreen.kt`, `ui/library/LibraryScreen.kt`, `ui/detail/AlbumScreen.kt`, `ui/detail/ArtistScreen.kt`, `ui/detail/PlaylistScreen.kt`, `ui/detail/MixScreen.kt`, `ui/detail/TrackRow.kt`, plus one `ViewModel` per screen
- Test: `src/androidTest/.../BrowseScreensTest.kt` (with a `FakeLibrary` implementing `LibrarySource`)

**Interfaces:**
- Consumes: `ShelfApi` methods (Task 3) behind `interface LibrarySource` (the same signatures, implemented by `ShelfApi`, so tests can fake it). Covers come from Task 2.
- Produces: each screen takes `onPlay: (tracks: List<Track>, index: Int, context: PlayContext) -> Unit`. `data class PlayContext(label: String, route: String)` is what Now Playing shows as "Playing from".

Content per screen:
- **Home:** greeting, a resume card (the first `recent` album), a "Made for you" row of `TapeCover`s, "Recently added" and "Rediscover" rows of `CaseCover`s.
- **Library:** chips for Playlists, Albums and Artists; Favourites pinned first; a list with the cover, title and subtitle.
- **Album:** a hero tinted with `albumColor`, the case cover, title (the size steps down for long titles, like `titleFit`), each artist as its own link (the `artists` list), year, songs and length, Play and Shuffle, then tracks with disc headers when `discNo > 1` exists.
- **Artist:** a header, Play, popular songs (5), releases, appears on.
- **Playlist and Mix:** the same layout as Album, with the tape for mixes.

- [ ] **Step 1:** Write the tests:
  - `albumListsTracksInOrder`
  - `tappingTrackPlaysFromIt` (`onPlay` called with the album's tracks and index 2)
  - `errorStateRetries` (`FakeLibrary` fails once with Offline: shows "Try again", tap it, the content appears)
  - `artistLinksOpenEachArtist` (the album "Aerosmith & Yungblud" with `artists = [Aerosmith, YUNGBLUD]` gives two clickable names)
  - `homeShowsMixTapes`
- [ ] **Step 2:** Run them. Expected: FAIL. **Step 3:** Implement. **Step 4:** Run them. Expected: PASS.
- [ ] **Step 5:** On the Redmi, browse the real library. Screenshot Home, an album, an artist, a playlist and a mix next to the same pages in the web app. Fix spacing, type and colour until it reads as the same product, with native feel.
- [ ] **Step 6:** Commit: "Android native: Home, Library, album, artist, playlist and mix screens".

### Task 6: The player service

**Files:**
- Create: `playback/PlaybackService.kt` (`MediaLibraryService`), `playback/MediaItems.kt`, `playback/PlayCounter.kt`, `playback/QueueStore.kt`, `playback/PlayerConnection.kt`
- Modify: `AndroidManifest.xml` (the service with `foregroundServiceType="mediaPlayback"`; permissions `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_MEDIA_PLAYBACK`, `POST_NOTIFICATIONS`, `WAKE_LOCK`, `INTERNET`)
- Test: `src/test/.../PlayCounterTest.kt`, `QueueStoreTest.kt`, `MediaItemsTest.kt`

**Interfaces:**
- Consumes: `ShelfApi.streamUrl/coverUrl/played`, `AppContainer.okHttp` (it carries the token), `Track`, `PlayContext`.
- Produces:
  - `fun Track.toMediaItem(api: ShelfApi, quality: String): MediaItem`: mediaId = `track.id.toString()`. The metadata holds the title, artist, album, artwork URI (512 px), duration, and extras `albumId` and `trackId`.
  - `class PlayCounter(onPlayed: (Int) -> Unit)` with `fun onTrackStarted(id: Int, durationS: Double)` and `fun onPosition(positionS: Double)`. Only forward steps of less than 2 s count as heard. It fires once when heard ≥ `min(240.0, duration/2)`.
  - `class QueueStore(file: File)` with `save(QueueSnapshot)` and `load(): QueueSnapshot?`. `@Serializable data class QueueSnapshot(tracks: List<Track>, index: Int, positionMs: Long, context: PlayContext?, shuffle: Boolean, repeat: Int)`.
  - `class PlayerConnection(context)`: connects a `MediaController`. It exposes `state: StateFlow<PlayerUi>` (`PlayerUi(current: Track?, previous: Track?, next: Track?, playing: Boolean, positionMs: Long, durationMs: Long, queue: List<Track>, index: Int, context: PlayContext?)`) and `play(tracks, index, context)`, `toggle()`, `next()`, `previous()`, `seekTo(ms)`, `skipTo(index)`.
  - Service behaviour:
    - ExoPlayer with `OkHttpDataSource.Factory(container.okHttp)` and a 500 MB `SimpleCache`
    - `setAudioAttributes(music, handleAudioFocus = true)`, `setHandleAudioBecomingNoisy(true)`, `setWakeMode(C.WAKE_MODE_NETWORK)`
    - session activity = `MainActivity`
    - the queue is saved on every item change and pause, and every 10 s while playing
    - restored (paused) in `onCreate` when the player is empty
    - `PlayCounter` is wired to `api.played`

- [ ] **Step 1:** Write the tests:
  - `PlayCounterTest.countsOnlyHeardTime` (a jump of +60 s doesn't count)
  - `firesOnceAtHalfOrFourMinutes` (300 s track fires at 150 s; 600 s track fires at 240 s; only once)
  - `restartingTrackCountsAgain`
  - `QueueStoreTest.queueStoreRoundTrip`
  - `loadMissingFileIsNull`
  - `MediaItemsTest.mapsMetadataAndArtwork`
- [ ] **Step 2:** Run them. Expected: FAIL. **Step 3:** Implement. **Step 4:** Run them. Expected: PASS.
- [ ] **Step 5:** Write the instrumented `restoresPausedAtSavedPosition`: save a snapshot (index 1, 42 s), start the service, connect a controller, and assert it's paused at index 1 within ±1 s of 42 s. Run it on the Redmi. Expected: PASS.
- [ ] **Step 6:** On the Redmi, play an album from the Album screen (a temporary button is fine). Check:
  - the notification and lock screen show the cover and controls
  - Bluetooth or headphone play/pause works
  - unplugging headphones pauses
  - swiping Shelf Preview away keeps playing, and `adb logcat | grep SwipeUpClean` doesn't stop the music
  - after a few minutes the play shows in the web app's history
- [ ] **Step 7:** Commit: "Android native: Media3 playback service, play recording, queue that survives restarts".

### Task 7: Mini player, Now Playing, queue and swipe to skip

**Files:**
- Create: `ui/player/SwipeToSkip.kt`, `ui/player/MiniPlayer.kt`, `ui/player/NowPlayingScreen.kt`, `ui/player/QueueSheet.kt`
- Modify: `ui/AppNav.kt` (fills the `miniPlayer` slot and adds the `nowPlaying` route), `MainActivity.kt` (creates the `PlayerConnection`), and the screens' `onPlay` wired to `PlayerConnection.play`
- Test: `src/androidTest/.../SwipeToSkipTest.kt`, `MiniPlayerTest.kt`

**Interfaces:**
- Consumes: `PlayerConnection.state` and its actions (Task 6), the covers (Task 2).
- Produces: `@Composable fun SwipeToSkip(previous: (@Composable () -> Unit)?, current: @Composable () -> Unit, next: (@Composable () -> Unit)?, onPrevious: () -> Unit, onNext: () -> Unit, modifier: Modifier)`. The neighbours follow your finger. Releasing past 35% of the width, or with a fling over 1200 dp/s, snaps over and calls the callback once, with a `HapticFeedbackType.SegmentTick`. Anything less springs back. If a neighbour is `null`, a drag towards it is resisted (rubber band) and always springs back.

Content:
- **Mini player:** cover, title over artist (one line each, ellipsized), play/pause, a thin progress line, and swipe to skip. Tapping it opens Now Playing.
- **Now Playing:** "Playing from {context}", a large cover (case, or the record when vinyl) with swipe to skip. The CD or record behind it spins slowly while playing, like the web app's `.disc-face`, and stops when reduced motion is on. title and artist (artist links), a scrubber with times, shuffle, previous, play/pause, next, repeat, and a queue button that opens `QueueSheet` (tap to jump). The background is tinted with the album colour.

- [ ] **Step 1:** Write the tests:
  - `swipeLeftPastThresholdGoesNext` (exactly one `onNext`)
  - `swipeRightGoesPrevious`
  - `shortSwipeDoesNothing` (20% and slow: no callbacks)
  - `flingSkipsEvenWhenShort`
  - `swipeAtQueueEndSpringsBack` (`next = null`, swipe left 60%: no callback)
  - `MiniPlayerTest.longTitleStaysOneLine` (a 200-character title with "Måneskin 日本語": the title node's line count is 1)
  - `tapOpensNowPlaying`
- [ ] **Step 2:** Run them. Expected: FAIL. **Step 3:** Implement. **Step 4:** Run them. Expected: PASS.
- [ ] **Step 5:** On the Redmi, swipe the mini player and the Now Playing cover both ways, quickly and slowly, at the first and last songs, and while the music plays. Expected: the music follows, there are no double skips, and you feel the haptic tick.
- [ ] **Step 6:** Commit: "Android native: mini player, Now Playing, queue, swipe to skip".

### Task 8: Milestone 1 check on the phone

**Files:**
- Create: `docs/superpowers/plans/2026-11-09-native-android-m1-check.md` (the results)

- [ ] **Step 1:** Build a release (`-PversionName=0.7.0-preview.1 -PversionCode=700`) and install it on the Redmi.
- [ ] **Step 2:** Run the checklist and record each result:
  - cold start to Home in under 1.5 s on Wi-Fi
  - sign out from the server side (change the password in the web admin), then the app returns to sign-in
  - turn the server off, then the error states show with "Try again"
  - play an album, lock the phone and leave it for 10 minutes: it keeps playing and the songs advance on the lock screen
  - swipe Shelf Preview away mid-song: no gap
  - force-stop while paused, then reopen: the same song and position, paused
  - swipe to skip at both ends
  - the old "Shelf" app still works
- [ ] **Step 3:** Fix anything that failed, using its owning task's test style, then commit the results file: "Android native: milestone 1 checked on the Redmi 9".
