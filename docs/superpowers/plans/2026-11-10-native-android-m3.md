# Native Android, Milestone 3: Devices, Polish and Switch-over — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** The native app replaces the WebView app as `app.shelf`. It can be the playing device or a remote over Connect, and it has the home-screen widget, Android Auto, the self-updater, first-run onboarding and the web admin pages inside it.

**Architecture:**
- **One Connect client** (`connect/ConnectClient`, OkHttp WebSocket) lives in the app container, shared by the player service and the screens.
- **When another device plays,** `PlaybackService` swaps its media session's player for a `RemotePlayer` (a Media3 `SimpleBasePlayer`). It mirrors the remote state and turns every control into a Connect `cmd`. So the screens, notification, lock screen, volume keys, widget and Android Auto all work as a remote with no changes of their own.
- **When this phone plays,** `ConnectBridge` reports ExoPlayer's state and runs incoming commands on it.
- **Widget:** RemoteViews whose buttons go through Media3's `MediaButtonReceiver`.
- **Android Auto:** a browse tree served by the `MediaLibraryService` callback.
- **Updater:** a port of the legacy `Updater` to Kotlin and OkHttp, run by JobScheduler.

**Tech Stack:** As M2. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-09-native-android-design.md` (milestone 3)

## Global Constraints

- **Everything from M1 and M2 still applies:** Shelf's look, copy rules, branding, and the token only sent to our server.
- **The Connect protocol is the server's** (`src/shelf/connect.py`):
  - Devices send `hello {id,name,kind}`, `rename`, `claim`, `state {state, queue?}`, `cmd {name,args}`, `transfer {to, snapshot?}` and `blocked`.
  - The server sends `welcome {you, devices, active, state, queue}`, `devices {devices, active}`, `state {state, queue?, from}`, `cmd`, `takeover {snapshot}`, `release`, `duplicate` and `notice {text}`.
- **Its shapes are the web app's** (`connect.js`):
  - `state` is `{index, track, playing, position (s), duration (s), shuffle (bool or "smart"), repeat ("off"|"all"|"one"), context {label, href}, volume 0..1}`.
  - `queue` is `{rev, tracks, original}`.
  - `snapshot` is `{queue, original, index, position, playing, shuffle, repeat, context}`.
  - Command names: playList(tracks, start, opts), playNext(tracks), addToQueue(tracks), jumpTo(i), removeAt(i), clearUpNext, toggle, play, pause, next, prev, seek(s), setVolume(v), toggleShuffle, cycleRepeat.
- **Device id:** 22 characters of `[A-Za-z0-9_-]`, kept in prefs `connect`.
  - Kind is `phone`, or `tablet` when smallestScreenWidthDp ≥ 600.
  - Name is `Settings.Global.DEVICE_NAME`, falling back to `Build.MODEL`.
- **Holding commands:** commands pressed while disconnected are sent after reconnecting, if they're under 60 s old. Reconnect backoff is 1, 2, 4… up to 30 s.
- **Context:** native routes map to web hrefs as `#/` + route, except `favourites` ↔ `#/liked`.
- **Switch-over:**
  - `applicationId "app.shelf"`, app name "Shelf", version 0.7.0 (700). That's above the WebView app's 0.6.0 (600), with the same signing key.
  - Keep the legacy component names that live on in the system: `app.shelf.MainActivity`, `app.shelf.NowPlayingWidget` (widgets already placed), `app.shelf.UpdateJob` (job id 41).
- **Updater:**
  - `https://api.github.com/repos/Spinjitsudoom/shelf/releases/latest`, every 6 h.
  - versionCode from the tag (`major*10000 + minor*100 + patch`).
  - Only an APK whose package and versionCode match is offered.
  - It does nothing in `app.shelf.preview`.
- **The DJ stays shelved:** no DJ page (owner's standing call).

## Review Focus

1. **The connection drops while this phone is a remote** (4G hand-off). Expected: controls still work, and presses within 60 s are sent on reconnect. *Test: Task 1 `heldCommandsSentAfterReconnect`, `staleCommandsDropped`.*
2. **The playing device goes away while this phone is its remote.** Expected: the phone takes over at that song and position, paused. *Test: Task 2 `activeGoneTakesOverPaused`.*
3. **Volume keys or the lock screen while the phone is a remote.** Expected: they change the other device's volume (0..1), not the phone's. *Test: Task 2 `volumeGoesToRemote`.*
4. **The same id is already connected** (a restored backup). Expected: the phone picks a new id and connects. *Test: Task 1 `duplicateTakesNewId`.*
5. **The updater gets an APK for another package, or an older one.** Expected: it's ignored and never offered. *Test: Task 6 `rejectsOtherPackageOrOlder`.*

---

### Task 1: Connect messages and client

**Files:**
- Create `connect/ConnectMessages.kt`, `connect/ConnectClient.kt`, `connect/DeviceIdentity.kt`.
- Modify `AppContainer` (`val connect`).
- Tests: `ConnectMessagesTest`, `ConnectClientTest` (MockWebServer WebSocket upgrade).

**Interfaces (produces):**
- `@Serializable data class DeviceInfo(id, name, kind)`.
- `data class RemoteState(index: Int, track: Track?, playing: Boolean, position: Double, duration: Double, shuffle: Boolean, repeat: String, context: WebContext?, volume: Double)`, parsed from JSON (`shuffle` true for `"smart"` too).
- `@Serializable data class WebContext(label: String, href: String? = null)`.
- `data class Snapshot(queue: List<Track>, index: Int, position: Double, playing: Boolean, shuffle: Boolean, repeat: String, context: WebContext?)`.
- `sealed interface Incoming`: Welcome, Devices, State, Cmd(name, args: JsonArray), Takeover, Release, Duplicate and Notice, from `fun parseIncoming(text: String): Incoming?`.
- `fun webHref(route: String): String` and `fun nativeRoute(href: String?): String?`.
- `data class ConnectUi(connected: Boolean, selfId: String, devices: List<DeviceInfo>, activeId: String?, state: RemoteState?, queue: List<Track>, at: Long)` with `val remote: Boolean` (another connected device is active).
- `class ConnectClient(identity: DeviceIdentity, okHttp, server: () -> String?, clock: () -> Long = System::currentTimeMillis)`:
  - `val ui: StateFlow<ConnectUi>`, `fun start()`, `fun stop()`
  - `fun send(json: JsonObject)`, `fun cmd(name: String, vararg args: JsonElement)` (held while disconnected)
  - `var listener: ConnectListener?` with `onCmd(name, args)`, `onTakeover(Snapshot)`, `onRelease()`, `onNotice(text)`

- [ ] Tests:
  - `parsesEveryIncomingKind`
  - `smartShuffleIsOn`
  - `routesAndHrefsMapBothWays` (`album/5` ↔ `#/album/5`, `favourites` ↔ `#/liked`)
  - `helloThenWelcomeFillsUi`
  - `heldCommandsSentAfterReconnect`
  - `staleCommandsDropped` (clock moved 61 s)
  - `duplicateTakesNewId`
- [ ] Implement, run the unit tests, commit and push.

### Task 2: The phone as playing device or remote

**Files:**
- Create `connect/RemotePlayer.kt` and `connect/ConnectBridge.kt`.
- Modify `PlaybackService`:
  - start the bridge;
  - on `remote`, `session.player = remotePlayer`, and back to ExoPlayer when it ends;
  - the user volume multiplies the levelling volume.
- Tests: `RemotePlayerTest`, `ConnectBridgeTest` (Robolectric).

**Interfaces:**
- Consumes Task 1.
- `class RemotePlayer(looper, client: ConnectClient, source: () -> LibrarySource?) : SimpleBasePlayer`:
  - The state comes from `client.ui`: a playlist of `toControllerItem` items, an extrapolating position, `DeviceInfo(PLAYBACK_TYPE_REMOTE, 0, 100)` with volume ×100, and shuffle/repeat.
  - Handlers send `play`/`pause`.
  - `seek` within the same song sends `seek(s)`; index+1 sends `next`, index−1 sends `prev`, and any other index sends `jumpTo`.
  - `setMediaItems` sends `playList(tracks, start, {context})`.
  - `addMediaItems` sends `playNext` at index+1, otherwise `addToQueue`.
  - `setDeviceVolume` sends `setVolume(v/100)`; shuffle sends `toggleShuffle`; repeat sends `cycleRepeat`.
- `class ConnectBridge(client, player: ExoPlayer, toItem: (Track, WebContext?) -> MediaItem)`:
  - Claims when ExoPlayer starts playing.
  - Reports `state` on changes and every 5 s, with the queue when the ids change.
  - Runs `cmd`s on ExoPlayer.
  - `takeover` loads the snapshot (playing as it says); `release` pauses.
  - When the active device disappears while remote, it loads the last remote state, paused.

- [ ] Tests:
  - `stateMapsToPlayer` (index, position, playing, shuffle, repeat)
  - `playPauseSendCmds`
  - `seekNextPrevJumpMapping`
  - `volumeGoesToRemote` (setDeviceVolume(40) → `setVolume 0.4`; DeviceInfo is remote)
  - `reportHasWebShape`
  - `commandsRunOnPlayer` (toggle, next, seek 30 → 30000 ms, jumpTo, setVolume clamps to 0..1)
  - `takeoverLoadsSnapshot`
  - `activeGoneTakesOverPaused`
- [ ] Implement, run the unit tests, commit and push.

### Task 3: Devices in the app

**Files:**
- Create `ui/player/DevicesSheet.kt`.
- Modify `NowPlayingScreen` (a devices button; "Playing on {name}" under the controls when remote) and `MiniPlayer` (a cobalt "Playing on {name}" line when remote).
- Test `DevicesSheetTest`.

**Interfaces:** `DevicesSheet(ui: ConnectUi, onPick: (id) -> Unit, onDismiss)`. "This phone" comes first, then the others. The active one is ticked; picking one sends `transfer {to, snapshot?}`. The snapshot comes from the local player when this phone is playing.

- [ ] Tests:
  - `listsThisPhoneFirstAndTicksActive`
  - `pickingSendsTransfer`
  - Copy: "Can’t reach the server to see your other devices" when not connected.
- [ ] Commit and push.

### Task 4: Home-screen widget

**Files:**
- Create `NowPlayingWidget.kt` (class `app.shelf.NowPlayingWidget`, the legacy component name), `res/layout/widget_now_playing.xml`, `res/xml/widget_now_playing.xml` and the backgrounds (ported from `android-legacy`).
- Modify `PlaybackService` (update the widget on track, play state and art; the art comes through Coil at 160 px) and the manifest (the receiver, plus `androidx.media3.session.MediaButtonReceiver`).
- Test `WidgetTextTest`.

**Interfaces:** `fun widgetText(track: Track?, playing: Boolean, device: String?): Pair<String, String>`. With nothing playing it gives "Shelf" / "Tap to open". When remote, the second line is "{artist} · on {device}". The buttons send `ACTION_MEDIA_BUTTON` KeyEvents (PLAY_PAUSE, NEXT, PREVIOUS) to `MediaButtonReceiver`.

- [ ] Tests: `nothingPlaying`, `playingHere`, `playingElsewhere`. Commit and push.

### Task 5: Android Auto

**Files:**
- Create `playback/LibraryTree.kt`.
- Modify `PlaybackService.Callback` (`onGetLibraryRoot`, `onGetChildren`, `onGetItem`, and `onSetMediaItems` expanding a tapped track to its list).
- Add `res/xml/automotive_app_desc.xml` and its manifest meta-data.
- Test `LibraryTreeTest`.

**Interfaces:**
- `class LibraryTree(source: LibrarySource)` with `suspend fun children(parentId: String): List<MediaItem>` and `suspend fun expand(mediaId: String): Pair<List<MediaItem>, Int>?`.
- Root ids: `home`, `mixes`, `playlists`, `albums`, `favourites`.
- Lists are `album:{id}`, `playlist:{id}`, `mix:{key}` and `favourites`. Tracks are `{parentId}|{trackId}`.

- [ ] Tests:
  - `rootHasFiveSections`
  - `albumChildrenArePlayableTracks`
  - `playFromAlbumQueuesWholeAlbum`
- [ ] Commit and push.

### Task 6: Updater

**Files:**
- Create `update/Updater.kt`, `update/UpdateJob.kt` (class `app.shelf.UpdateJob`, job id 41) and `update/UpdateActivity.kt` (PackageInstaller session).
- Modify the manifest (`REQUEST_INSTALL_PACKAGES`, the job service, the activity) and `SettingsScreen` (About: "Check for updates" with the result).
- Test `UpdaterTest`.

**Interfaces:**
- `fun versionCode(tag: String): Int`
- `fun apkAsset(release: JsonObject): String?`
- `fun shouldOffer(mine: Int, latest: Int, apkPackage: String?, apkCode: Int?, myPackage: String): Boolean`
- `suspend fun Updater.check(force: Boolean): UpdateResult` (UpToDate, Ready(version), Failed)

- [ ] Tests:
  - `versionCodeFromTag` ("v0.7.1" → 701, "0.10.0" → 1000)
  - `picksApkAsset`
  - `rejectsOtherPackageOrOlder`
- [ ] Commit and push.

### Task 7: Onboarding, upgrade note, and web pages inside the app

**Files:**
- Create `ui/start/Onboarding.kt` and `ui/web/WebPageScreen.kt`.
- Modify `StartViewModel`: an `upgradeNote` when a server is saved but there's no token and the native marker is missing. The note says "Shelf has a new look. Sign in once more. Anything downloaded in the old app needs downloading again."
- Modify `MainActivity` (onboarding once after the first sign-in), `AppNav` (route `web/admin`) and `SettingsScreen` ("Admin dashboard" for admins).

**Interfaces:**
- Onboarding is "Keep the music playing". It asks Android to leave Shelf running in the background (`ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS`) and, on Android 13+, to show notifications. On MIUI it adds the Autostart hint. It's shown once (`prefs shelf: onboarded`).
- `WebPageScreen(url, token)` sets the cookie `shelf_session=token` for the server, loads `{server}/#/admin`, and Back goes back in the page before closing it.

- [ ] Tests: `upgradeNoteAfterWebViewApp`, `noUpgradeNoteOnFreshInstall` (StartViewModelTest). Commit and push.

### Task 8: Switch-over

**Files:**
- Modify `android/app/build.gradle.kts` (`app.shelf`, version 0.7.0/700) and `strings.xml` ("Shelf").
- Modify `.github/workflows/release.yml`: the android job builds `android/` with Gradle and signs with `SHELF_KEYSTORE` from the existing secret; the APK is `Shelf-{version}.apk`.
- Modify README and docs that name `android-legacy`, and remove `android-legacy/`.

- [ ] Build a release APK locally. `aapt2 dump badging` shows `package: name='app.shelf' versionCode='700'`. Commit and push.
- [ ] Phone (the owner says when): Connect both ways with a browser, volume keys as a remote, the widget, onboarding, the admin page. Ask the owner before installing `app.shelf` over the WebView app on the Redmi, and before tagging a release. Record the results in `-m3-check.md`.
