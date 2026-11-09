# Shelf for Android, native

*Design, 2026-11-09. Status: waiting for approval.*

## Why

Shelf's Android app today is the web app inside a WebView. It works, but it doesn't feel
like a finished product, and it can't be as dependable as Spotify. The music plays inside the
web page, so it's only as reliable as that page: MIUI kills the page's process when the app
is swiped away (Shelf recovers, with a gap of about 4 seconds), the battery cost is higher,
and Android Auto isn't possible.

The owner wants **a professional-feeling, professional-looking final product, as reliable as
Spotify.** So the Android app is rebuilt natively: native screens, and Android's own media
engine playing the music in a background service that outlives everything else.

## Goals

- **Reliability on a par with Spotify.** Music never stops because the screen locked, the app
  was swiped away, MIUI tidied up, or the network blipped. Lock screen, notification,
  headphones, Bluetooth, car displays and Android Auto all work.
- **A polished, native feel.** Fast to open, smooth 60/120 Hz scrolling, real Android
  gestures, predictive back, transitions between screens, proper loading and empty and error
  states, and no web-page tells (text selection, rubber-banding, blank flashes).
- **Shelf's own look,** carried over from the web app: jewel cases (and the vinyl option),
  mix tapes, cobalt accent, Archivo and Caveat type, pages tinted by the album's colour. It
  must not look like Spotify: no green, no copies of Spotify's icons or the Liked Songs
  gradient, and the names Favourites and Shelf Mix. Generic labels the web app already uses
  (Made for you, On Repeat, Blend, Friend activity, Smart shuffle, Your Library) are fine.
- **Everyday listening at least as complete as today's app**, before it replaces it.

## Non-goals

- Replacing the web app. Browsers and the desktop players keep using it; the server and its
  API stay the source of truth.
- Rebuilding admin and maintenance natively (the admin dashboard, uploads, CD ripping, the DJ's
  settings, music folders). These open the web app's pages inside the native app, signed in.
- iOS.

## Anti-goals (it fails, even if it works, if…)

- It drops features people use today, such as remote control, downloads, Favourites,
  playlists or mixes, when it replaces the current app.
- It looks like a generic Material template, or like Spotify.
- Updating to it loses the sign-in or the downloads people already have. At the least it must
  sign in once and re-download, with a clear message.

## Decided

- **Native Kotlin app** using Jetpack Compose and Material 3 components, styled with Shelf's
  own theme (decided with the owner).
- **Android's media engine for playback:** Media3 (ExoPlayer) in a `MediaLibraryService`. This
  gives the notification, lock screen, Bluetooth, Android Auto (the same browse tree) and
  background survival.
- **It updates itself from GitHub releases,** like the current app (`Updater` behaviour:
  background check, notification, Android's install prompt).
- **The same package name (`app.shelf`) and signing key** once it replaces the current app, so
  it installs over it.

## My calls (the owner can overrule these)

1. **Built alongside, then switched over.** Until it matches today's app for everyday
   listening, the native app installs next to the current one as **"Shelf Preview"**
   (`app.shelf.preview`), so the working app is never broken mid-build. At parity, the release
   switches to `app.shelf` and replaces the WebView app.
2. **Minimum Android 8.0 (API 26).** That covers the Redmi 9 and nearly every phone in use,
   and keeps the code simpler. The Nexus 10 (Android 5) is left out.
3. **Libraries:** OkHttp for HTTP and the device WebSocket, kotlinx.serialization for JSON,
   Coil for album art, Media3 (ExoPlayer, session, downloads, cast-ready), Room for the
   download and offline index, WorkManager for update checks and download jobs, and Navigation
   Compose. No heavy DI framework: one small app container.
4. **Sign-in uses the API's token** (`POST /api/login` returns `token`, sent as
   `Authorization: Bearer`). Web-app pages shown inside the app get the same token as the
   `shelf_session` cookie, so they're signed in too.
5. **Dark first,** with a light theme and a follow-the-system option, as on the web.

## How it works

### Playback

- ExoPlayer streams `GET /api/tracks/{id}/stream?q=<quality>`, with the same qualities as the
  web settings and a smaller one on mobile data. A disk cache holds recently played songs.
- **Gapless** between songs by default. **Volume levelling** uses each track's `lufs` and
  `peak` from the API (the web app's "Normalize volume" setting), applied as a gain on the
  player.
- **Crossfade, and Mix's beat-matched transitions (with the playlist's per-song
  transition styles),** are rebuilt for the native player in milestone 4: two players, with
  volume and EQ curves driven by the API's `mix` points.
- **Equalizer and mixer:** a 6-band EQ with the web app's presets (including Metal), using
  Android's audio effects or a Media3 audio processor (milestone 4).
- The `MediaLibraryService` owns the queue, so the screens are only a view of it. Closing,
  swiping away or MIUI's clean-up can't touch it, because the service runs in the foreground
  while music plays.

### Devices (remote control)

A native client of the server's `/api/connect` WebSocket protocol: `hello`, `welcome`,
`devices`, `state` (with `queue`), `cmd`, `claim`, `transfer`, `takeover`, `release`,
`notice`, `blocked`, `rename`. The phone can be the playing device (it reports its state) or a
remote (its controls send `cmd`). As a remote, its media session switches to remote playback,
so the volume buttons and the lock screen control the other device; this already works in
today's app. It reconnects on its own, and holds commands pressed while disconnected (as
`connect.js` now does).

### Offline

Downloads of an album, a playlist or Favourites, using Media3's download manager with the
index in Room. With no connection, the app opens to what's downloaded and plays it.

### Screens (each with loading, empty and error states)

- Server address, then sign in, then first-run onboarding (the background-play permission
  prompt, explained once).
- **Home:** resume hero, Mixes for you (tapes), recently added, new from your artists.
- **Library:** playlists, albums and artists, with Favourites pinned, filters, sort and a
  CD/vinyl toggle.
- **Album:** jewel-case hero tinted by the album colour, tracks, quality badge, download.
- **Artist:** photo header, popular songs, releases, appears on, about.
- **Playlist:** edit, reorder, add songs with suggestions, share, Mix on/off.
- **Mix and radio** pages (the tape cover).
- **Search,** with recent searches.
- **Now Playing:** big cover (with the CD or record spinning), scrubber, controls, queue,
  lyrics (synced), device picker, sleep timer, video button (opens the YouTube app).
- **People and shared mixes,** Settings (listening, account, appearance, downloads), About.
- **Home-screen widget** (as today), and **Android Auto** (browse Home, Library and Mixes, and
  play).
- **Web pages inside the app:** Admin, uploads, CD ripping, the DJ.

## Milestones

Each milestone is installable on the Redmi as Shelf Preview and checked there before the next.

1. **Foundation and playing music:** project, theme, typography, cover components (case,
   vinyl, tape), sign-in, Home, Library, Album, Artist, Playlist (read-only), the player
   service with notification, lock screen and background play, a mini player, Now Playing and
   the queue.
2. **Everyday parity:** search, Favourites, playlist editing, mixes and radio, lyrics,
   downloads and offline, settings, normalisation, history and scrobbling (the server already
   records plays sent to it).
3. **Devices and polish:** remote control both ways, the widget, Android Auto, the updater,
   onboarding, the web pages inside the app. **Switch-over:** release as `app.shelf`,
   replacing the WebView app.
4. **Extras:** crossfade, Mix transitions, the equalizer and mixer, people and shared mixes,
   music videos, sleep timer and the remaining settings.

## Build and release

- Gradle (wrapper checked in), Kotlin and the Compose BOM, with versions pinned and at least
  two weeks old. It lives in `android/` (the old WebView app moves to `android-legacy/` until
  the switch-over, then it's removed).
- CI builds and signs it with the same `ANDROID_KEYSTORE_BASE64` secret. The versionCode
  keeps the current scheme (`major*10000 + minor*100 + patch`).
- Tests: unit tests for the API client, the Connect protocol and queue logic, Compose UI tests
  for the main screens, and a check on the real phone at each milestone.

## Left to the builder

The exact component structure, animation curves, the cache sizes and how the Room schema is
laid out, provided the goals and anti-goals hold.
