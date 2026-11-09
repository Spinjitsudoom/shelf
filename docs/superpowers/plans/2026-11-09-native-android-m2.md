# Native Android, Milestone 2: Everyday Parity — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Shelf Preview does everything people do every day in today's app: search, Favourites, playlist editing, song and artist radio, lyrics, offline downloads and settings, plus instant starts for lossless songs on mobile data.

**Architecture:** This builds on M1 (`android/`). New API calls go on `ShelfApi`/`LibrarySource`. Per-device settings live in `SettingsStore` (SharedPreferences, exposed as a StateFlow). Likes live in a `LikesStore` that the screens observe. The song actions sheet (`SongMenu`) is shared by every list. Downloads use Media3's `DownloadManager` (the same cache layout the player reads), with a Room-free JSON index of what's downloaded. On the server, `transcode.py` streams a conversion while it's being written.

**Tech Stack:** As M1, plus `androidx.media3:media3-exoplayer` download classes (already in it). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-09-native-android-design.md` (milestone 2)

## Global Constraints

- Everything in M1's Global Constraints still applies (`app.shelf.preview`, Shelf's look, copy rules, branding rules, the token only to our server).
- Settings defaults:
  - Wi-Fi quality `original`
  - mobile-data quality `auto` (= `streamQuality` from M1)
  - normalise on, level `normal`
  - theme `dark`
  - format `cd`
- Loudness targets (dB LUFS), from `settings.js`: loud −11, normal −14, quiet −19.
  - gain = target − lufs, clamped to [−24, +12].
  - For normal and quiet, gain ≤ −1 − peak.
  - In album context (not shuffled, playing from an album page), use the album's loudness.
- Lyrics come from `GET /api/tracks/{id}/lyrics` → `{kind: synced|plain|instrumental|none, lines:[{t,text}], text}`.
- Playlist edits use the server's routes:
  - `POST /api/playlists {name}`
  - `PATCH /api/playlists/{pid} {name,description}`
  - `DELETE /api/playlists/{pid}`
  - `POST /api/playlists/{pid}/tracks {trackIds}`
  - `DELETE /api/playlists/{pid}/tracks/{entryId}`
  - `PUT /api/playlists/{pid}/order {entryIds}`
- Likes: `GET /api/likes/ids`, `PUT /api/likes/{id}`, `DELETE /api/likes/{id}`.
- Radio: `GET /api/radio?track=` or `?artist=` → a mix-shaped object.
- Search: `GET /api/search?q=` → `{artists, albums, tracks}`.

## Review Focus

1. **A like or playlist edit made with no connection.** Expected: it says it couldn't be saved and the heart goes back, never silently lost. *Test: Task 3 `likeRollsBackWhenOffline`.*
2. **Downloads with storage full or the connection dropping mid-album.** Expected: what finished stays playable, the rest is marked not downloaded, and there's no crash. *Test: Task 7 `failedDownloadNotMarkedComplete`.*
3. **Search typed fast.** Expected: only the latest query's results show, never results for a stale query. *Test: Task 4 `staleResultsIgnored`.*
4. **Lyrics lines at the same time, or an empty song.** Expected: the right line is highlighted, with no crash on the first or last line. *Test: Task 6 `activeLineAtBoundaries`.*
5. **A server conversion that fails halfway** (ffmpeg error). Expected: the client gets an error and no half-file is cached for next time. *Test: Task 1 `failedTranscodeLeavesNoCache`.*

---

### Task 1: Server: stream conversions as they're made

**Files:** Modify `src/shelf/transcode.py` and the `/api/tracks/{id}/stream` route in `src/shelf/app.py`. Test `tests/test_transcode_stream.py`.

**Interfaces:**
- Produces `async def stream_transcode(dir, src, mtime, kbps, cache_mb) -> AsyncIterator[bytes]`. It yields bytes as ffmpeg writes them (fragmented MP4: `-movflags +frag_keyframe+empty_moov+default_base_moof`), and keeps a copy that becomes the cached file only when ffmpeg exits 0. When a finished copy is already cached, the route serves it with Range support, as today.

- [ ] Test `firstBytesArriveBeforeConversionEnds` (a 60 s sine FLAC: the first chunk is received while ffmpeg is still running, and the whole response is a valid MP4).
- [ ] Test `secondRequestServesCachedFile` (Range works).
- [ ] Test `failedTranscodeLeavesNoCache` (a corrupt source gives no cache file).
- [ ] Implement, run `pytest -q`, commit and push.

### Task 2: Settings, theme and volume levelling

**Files:** Create `settings/SettingsStore.kt`, `ui/settings/SettingsScreen.kt`, `playback/Loudness.kt`. Modify `PlaybackService` (quality from settings; `player.volume` from the gain for each song), `Theme`, `AppNav` (a settings button in the Home header) and `MainActivity`. Test `SettingsStoreTest`, `LoudnessTest`.

**Interfaces:**
- `data class Settings(wifiQuality: String = "original", dataQuality: String = "auto", normalize: Boolean = true, loudness: String = "normal", theme: String = "dark", format: String = "cd")`.
- `class SettingsStore(prefs)` with `val settings: StateFlow<Settings>` and `fun update(transform: (Settings) -> Settings)`.
- `fun gainDb(lufs: Double?, peak: Double?, level: String): Double` (0 when lufs is null).
- `fun volumeFor(gainDb: Double): Float = min(1, 10^(gainDb/20))`.
  - Ruling: only cuts are possible, because `player.volume` can't go above 1. Loud songs come down to meet quiet ones; quiet ones aren't boosted.

Settings screen sections:
- **Listening:** quality on Wi-Fi, quality on mobile data, normalise, level.
- **Appearance:** theme (dark, light, follow the phone); CD or vinyl.
- **Account:** signed in as {name} on {server}; Change server; Sign out.
- **About:** app version and server version.

- [ ] Tests:
  - `gainMatchesWeb` (lufs −8, peak −0.1, normal → −6.0; quiet −19 caps at −1 − peak)
  - `nullLufsIsZero`
  - `volumeNeverAboveOne`
  - `settingsPersistAndEmit`
- [ ] Implement the settings screen, the theme (light, dark, system) wired into `ShelfTheme`, and vinyl (`CaseCover(vinyl=)` everywhere). Commit.

### Task 3: Favourites and the song menu

**Files:** Create `data/LikesStore.kt`, `ui/common/SongMenu.kt` (a bottom sheet). Modify `TrackRow` (long-press and a ⋯ button open `SongMenu`), Now Playing (a heart next to the title) and `ShelfApi` (likeIds/like/unlike). Test `LikesStoreTest`.

**Interfaces:**
- `class LikesStore(api: () -> ShelfApi?, scope)` with `val ids: StateFlow<Set<Int>>`, `suspend fun refresh()`, and `fun toggle(id: Int, onError: (String) -> Unit)`. The toggle is optimistic; it rolls back and calls `onError("Couldn’t save that. Check the connection and try again.")` on failure.
- `SongMenu(track, actions)` actions:
  - Play next
  - Add to queue
  - Add to Favourites / Remove from Favourites
  - Add to playlist…
  - Song radio
  - Go to album
  - Go to artist (one per artist)
  - Remove from this playlist (only when it can be edited)
- `PlayerConnection` gains `playNext(tracks)` and `addToQueue(tracks)`.

- [ ] Tests:
  - `toggleIsOptimistic`
  - `likeRollsBackWhenOffline`
  - `refreshLoadsIds`
- [ ] Implement and commit.

### Task 4: Search

**Files:** Create `ui/search/SearchScreen.kt`, `ui/search/SearchViewModel.kt`. Modify `ShelfApi.search(q)`, `Models` (`SearchResults(artists, albums, tracks)`) and the `AppNav` bottom bar (Home, Search, Library). Test `SearchViewModelTest`.

**Interfaces:** `SearchViewModel(source)` with `query: StateFlow<String>`, `results: StateFlow<Load<SearchResults>?>` and `fun onQuery(q)` (debounced 250 ms; only the latest query's answer is kept).

- [ ] Tests:
  - `debouncesTyping`
  - `staleResultsIgnored`
  - `blankQueryShowsNothing`
- [ ] Screen:
  - a search field with focus and the keyboard on opening
  - top results: artists (round), then albums (cases), then songs (rows with menu)
  - recent searches kept locally (the last 8)
- [ ] Commit.

### Task 5: Playlists: create, edit, add, remove, reorder; radio

**Files:** Modify `ShelfApi` (createPlaylist, editPlaylist, deletePlaylist, addToPlaylist, removeFromPlaylist, reorderPlaylist, radio), `PlaylistScreen` (edit mode: rename, delete, drag to reorder, remove), `LibraryScreen` (+ New playlist), `ArtistScreen` (Radio button), and `AppNav` (the `radio/track/{id}` and `radio/artist/{name}` routes reusing `MixScreen`'s layout). Create `ui/common/AddToPlaylistSheet.kt`. Tests go in `ShelfApiTest` (request shapes) and `PlaylistEditTest` (reorder computes `entryIds` in the new order).

- [ ] Tests:
  - `createPlaylistSendsName`
  - `addToPlaylistSendsTrackIds`
  - `reorderSendsEntryIdsInNewOrder`
  - `radioByTrackAndArtist`
- [ ] Implement and commit.

### Task 6: Lyrics

**Files:** Create `ui/player/LyricsPanel.kt` and `ui/player/LyricsLogic.kt`. Modify Now Playing (a lyrics button that swaps the cover for lyrics, scrolling to follow) and `ShelfApi.lyrics(id)`. Test `LyricsLogicTest`.

**Interfaces:** `fun activeLine(lines: List<LyricLine>, positionS: Double): Int` (−1 before the first line).

- [ ] Tests:
  - `activeLineAtBoundaries` (before the first, exactly on a line, between lines, after the last, two lines at the same time → the later one)
  - `emptyIsMinusOne`
- [ ] Panel:
  - synced lines with the current one bright, the past dimmed, the future muted
  - tap a line to seek there
  - plain lyrics as text
  - "Instrumental" or "No lyrics for this song" when there are none
- [ ] Commit.

### Task 7: Downloads and offline

**Files:**
- Create `downloads/Downloads.kt` (Media3 `DownloadManager` over the same `SimpleCache` the player uses, and `DownloadService`) and `downloads/DownloadIndex.kt` (JSON: collections of {kind, id, name, tracks}).
- Modify the album, playlist and Favourites headers (a download button with a progress ring), Library (a "Downloaded" filter) and `PlaybackService` (it plays from the cache when offline; the cache is shared already).
- Test `DownloadIndexTest`.

**Interfaces:**
- `class DownloadIndex(file)` with `add(collection)`, `remove(kind,id)`, `all()` and `isDownloaded(kind,id)`.
- `Downloads.download(collection)`, `Downloads.remove(collection)` and `Downloads.progress: StateFlow<Map<String, Float>>`.
- Downloads use the stream URL for the Wi-Fi quality setting. When offline, screens fall back to the index for downloaded collections.

- [ ] Tests:
  - `indexRoundTrip`
  - `failedDownloadNotMarkedComplete` (a collection is complete only when every track's download state is COMPLETED)
  - `removeForgetsCollection`
- [ ] Phone: download an album, switch on airplane mode, and it still plays and browses Downloaded. Commit.

### Task 8: Polish and phone check

- [ ] Restyle the seek bar: a thin track with a round handle in Shelf's ink colour.
- [ ] Build `0.7.0-preview.5`, install it on the Redmi, and check:
  - search
  - like and unlike
  - create a playlist, add, reorder, remove
  - song radio
  - lyrics
  - settings (theme and vinyl)
  - downloads in airplane mode
  - a lossless song on mobile data starting quickly
- [ ] Record the results in `docs/superpowers/plans/2026-11-09-native-android-m2-check.md`. Commit and push.
