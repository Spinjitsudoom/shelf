# Shelf: what it is and everything it does

A reference for anyone (or any Claude session) working on this project. The user-facing pitch
lives in README.md; this is the complete inventory, with the file that owns each feature, plus
the project's standing decisions. Update it when features land or decisions change.

Last updated: 2026-11-12, after v0.7.8 shipped.

## The shape of the project

- **What:** a self-hosted music server for the owner's CD rips, with the features of a big
  streaming app, for a household of accounts. Public repo: github.com/Spinjitsudoom/shelf,
  AGPL-3.0-or-later. Latest release: **v1.0.3** (2026-11-13).
- **Server:** Python 3 + FastAPI + SQLite, in `src/shelf/`. Runs on Windows (installer,
  PyInstaller + Inno Setup) and Linux (`install.sh`: uv + systemd user service). ffmpeg does all
  audio work; Essentia analyses where available (not on Windows — `dsp.py` is the numpy fallback).
- **Web app:** plain ES modules, no framework or build step, in `src/shelf/web/` (`js/*.js`,
  one `style.css`, `index.html`, service worker `sw.js` — bump its `shelf-shell-vNN` cache name
  on every web change). Desktop three-pane layout; phones get a tab bar. PWA, installable.
- **Android:** two apps in `android/` — **Shelf** (`app.shelf`, native Kotlin + Compose +
  Media3) and **Shelf Lite** (`app.shelf.lite`, a thin WebView wrapper). minSdk 26.
  versionCode = major*10000 + minor*100 + patch.
- **Desktop player:** Electron wrapper in `desktop/`, shipped as Windows installer, .deb and
  Flatpak.
- **Tests:** `tests/` (pytest, ~250) and `android/app/src/test` (~200). CI runs tests on every
  push; a `v*` tag builds and publishes everything (`.github/workflows/release.yml`).

## Library and files (server)

- **Scanning** (`scanner.py`, `tags.py`, `db.py`): walks the music folders, reads tags, watches
  for changes; incremental rescans. Folders are managed in Settings (`folders.py`).
- **Covers** (`covers.py`): lookup, resizing, caching, per-album accent colour.
  **Cover finder** (`coverfix.py`): fills missing/small covers from MusicBrainz + Cover Art Archive.
- **Shared credits** (`credits.py`): "A & B" tags split into both artists' pages.
- **Genres** (`genres.py`): the tag's genres plus the artist's from MusicBrainz.
- **Getting music in:** browser uploads incl. ZIPs (`uploads.py`), a watch folder that files
  dropped music by its tags (`watch.py`), CD ripping on the server's drive (`ripper.py`),
  **playlist import** (`imports.py`): Spotify/YouTube playlist links (public pages, first 100
  songs), M3U/PLS/XSPF/CSV/Spotify-data-JSON/pasted text, fuzzy-matched against the library.
- **Library health** (`health.py`, admin): same artist+title duplicates; fake lossless
  (`lossy.py`, spectral cutoff < 19 kHz); **the same recording under another name**
  (`fingerprint.py`, Chromaprint via ffmpeg, bit-error threshold 0.07) — report only, never
  changes files.
- **Analysis in the background:** loudness/ReplayGain (`loudness.py`, EBU R128), tempo + key
  (`analysis.py` Essentia / `dsp.py` numpy), "sounds like" fingerprint (`sound.py`, ~50 numbers),
  waveform peaks for the transition editor (`peaks.py`).

## Playing

- **Streaming:** original quality by default; transcodes (AAC 96/128/192/320) picked at load
  time (`transcode.py`); Android falls back to 320k AAC when the phone lacks a FLAC/ALAC decoder.
- **Queue:** add/next, Smart Shuffle suggestions, clear-up-next, autoplay of similar songs when
  it runs out; reorder by dragging on Android (`QueueMove.kt`) and on the web
  (`queuedrag.js`, since 0.7.7) — moves relay over Connect when another device plays.
- **Mix transitions:** beat-matched crossfades with a DJ-style editor over both waveforms
  (`transitions.js`, `transition-editor.js`, `dsp` on Android in `Transition.kt`/`Decks.kt`).
- **Connect** (`connect.py`, web `connect.js`, Android `connect/`): every open Shelf is a
  device; play on one, control from another; queue and position hand over between devices.
- **Party mode** (`party.py`): others join "X's party", add songs, vote to skip.
- **Podcasts** (`podcasts.py`, web `podcasts.js`, Android `PodcastScreens.kt`): follow shows by name
  (Apple's free podcast directory, `itunes.apple.com/search`) or by pasting a link: the RSS feed,
  a Podbean show page (`<name>.podbean.com` → `feed.podbean.com/<name>/feed.xml`), an Apple
  Podcasts page (lookup API), or any page with `<link rel=alternate type=application/rss+xml>`.
  Feeds are stored once (`podcasts`, `episodes`), followed per person (`podcast_subs`), checked
  every 2 h while followed (`Refresher`), and dropped when nobody follows them and nobody kept an
  episode of them. **Your Episodes** (`episode_saves`, `/api/podcasts/saved`, web `#/episodes`,
  Android `YourEpisodesScreen`): a bookmark on each episode keeps it there; a download button
  keeps it on the device (web IndexedDB collection kind "episode", Android `Downloadable` kind
  "episode") and saves it too; taking an episode out deletes its download. Pinned in the Library
  under Favourites, with Unplayed / Downloaded / In progress filters and Recently added or
  Release date order; offline it lists what's downloaded. **Episodes are
  tracks with ids ≥ 1,000,000,000** (`EP_BASE` + episode id) and show artwork is album
  `SHOW_BASE` + show id, so queue, Connect, lock screen, Android downloads and resume work
  unchanged; `/api/tracks/{id}/stream` proxies the audio from the host (Range passed through),
  `/resume` keeps the place in `episode_state` (near the end = finished), and played/skipped are
  no-ops, so podcasts stay out of stats and recommendations. Only public-internet addresses are
  fetched (redirects re-checked). No crossfade into or out of an episode; no Favourites or
  playlists for episodes. Woven into the rest of the app rather than kept on its own page: the
  main search (web and Android) also finds your shows and their episodes, plus "Podcasts to
  follow" from the directory with a one-tap Follow (`/api/podcasts/search?live=1`, a moment
  after typing stops, cached an hour, only when online lookups — `artist_info` — are on); Your
  Library lists followed shows with a Podcasts chip and "Find a podcast" (web and Android); Home's
  "Your podcasts" row shows episodes in progress, new ones from the last two weeks, and otherwise
  the newest unheard episode of each show. There's no Podcasts button any more: the page (`#/podcasts`) is
  reached from Home's "See all" and the Library's "Find a podcast". A link pasted into search is
  always read, even with online lookups off.
- **Extras:** per-device equalizer + mixer screen with live spectrum (`mixer.js`,
  `EqualizerScreen.kt`), visualizer (`visualizer.js`, `Visualizer.kt`), sleep timer, lyrics
  (`lyrics.py`: LRCLIB and tags, synced where possible), music videos via YouTube lookup
  (`videos.py`), resume points for tracks ≥ 15 min (`resume.py`), volume normalization,
  skip-on-error, crossfade-safe shuffle order.
- **Offline** (web `offline.js`, Android `downloads/`): download albums, playlists, Favourites;
  plays with no connection.

## Recommendations (classic algorithms only — a standing decision: no AI models)

- **Made for you** (`mixes.py`): Shelf Mixes, On Repeat, Rediscover, Discover; song and artist
  radio. Matched on sound fingerprint, artist, genre, tempo, key.
- **Home shaped by taste** (`home.py`, `/api/home` → `rows`): "More like <artist>" rows for two
  of your top four artists (plays with a 30-day half-life, likes, +3 for a followed artist; a
  different pair each day), filled by `_recommend` and cached per person per day; "From artists you
  follow" (added in the last month first, then least played). The row order is a base weight
  per row plus how often you come back to it (`home_taps`, POST `/api/home/used`, once per half hour
  at most, two-week half-life; not sent in a private session). Little listening yet (< 20 plays in
  30 days): Recently added moves up. Web and Android draw rows in the server's order; offline
  Android falls back to the fixed rows.
- **Mood mixes** (`moods.py`): Workout, Chill, Party, Feel Good, Melancholy, Heavy.
- **Together** (`together.py`): co-occurrence from shared playlists and listening sessions;
  Blends and Friend activity.
- **Feedback** (`feedback.py`): skips (< 30 s) and removed suggestions teach the recommenders.
- **Playlist from words** (`playlist_maker.py`): "metal, high energy" → matched against what
  Shelf knows, no LLM.
- **Smart playlists** (`smart.py`): rule-based, re-evaluated on open.
- **New releases** (`releases.py`): albums the owner's artists have out that the shelf lacks.
- **Stats + Wrapped** (`stats.py`): listening stats in the listener's own time zone, yearly
  Wrapped.

## People and accounts

- **Auth** (`auth.py`): accounts with per-user Favourites, playlists, history, devices; admin
  role; per-user app passwords for Subsonic.
- **Sharing:** shared/collaborative playlists; **share links** (`shares.py`): public, optional
  expiry, off until an admin enables.
- **Scrobbling:** ListenBrainz per user (`scrobble.py`); Last.fm support exists (`lastfm.py`)
  but is **deferred** — no API keys yet. AcoustID is likewise deferred.
- **Following artists** (`follows.py`): a Follow button on the artist page (web and Android);
  stored as the Subsonic artist star (`stars` table, kind 'artist', folded name), so starring an
  artist in a Subsonic app is the same thing. Once you follow anyone, **Your Library** (web side
  panel, Android Library tab) keeps to playlists, followed artists and their albums; until then it
  shows everything with a hint. Web: the library's sort menu has "What you follow / Everything on
  the server" (per device), and right-clicking an artist there offers Unfollow. Android: "Show
  everything" next to the Library title. The web Albums/Artists pages still show the whole shelf.
- **Requests** (`requests.py`, web `requests.js`, Android opens it in a web view from the "Request music" button on Home):
  anyone asks for an artist or one album, with an optional note; the whole household sees the
  list. Refused when it's already on the shelf or someone already asked. Admins mark requests done,
  declined or open again; a scan that brings the music marks matching requests done by itself.
  You withdraw your own; admins can withdraw anyone's. Reached from the top bar, the account menu,
  an empty search and the "Not on your shelf" page (each album there has a one-tap Request).
  **Linked to MusicBrainz:** while typing, the form suggests artists, then the picked artist's
  official albums/EPs (`release-group-status=website-default`, no bootlegs) or albums by title;
  a picked one stores its MusicBrainz ids, year and type, shows its cover and links to it.
  Lookups go through `releases.mb()`, the one shared, rate-limited MusicBrainz caller; they're off
  with `artist_info`, and typing a name MusicBrainz doesn't know still makes a request.
- **Artist pages** (`artists.py`): Wikipedia biography + photo (name only is sent out).

## Admin and operations

- **Admin dashboard** (web `admin.js`): people, services, library health, fingerprint progress,
  database backups (`backups.py`, daily), server updates (`updates.py`, checks GitHub every 6 h,
  one-click update), secure address, webhooks.
- **Secure address** (`secure.py`, web `secure.js`, Android `SecureMove.kt`): Tailscale
  Funnel/own-https so nothing crosses the internet in the clear; apps migrate to the new
  address by themselves. *Owner still has to press Turn on after updating the Windows server,
  then close the router's 4533 port forward.* Never run `tailscale funnel` on the dev Linux box.
- **Webhooks** (`webhooks.py`, web `webhooks.js`, admin-only): POST JSON to any URL on
  playing / paused / played / library events; optional HMAC-SHA256 signature
  (`X-Shelf-Signature`); listening events only for the admin's own account. Built for Home
  Assistant.
- **Subsonic API** (`subsonic.py`, `subsonic_more.py`): `/rest`, so Symfonium, Feishin, Substreamer,
  DSub work. Every Subsonic/OpenSubsonic call is answered (checked against the spec repo
  opensubsonic/open-subsonic-api, 2026-11): podcasts are Shelf's own (channel `pc-<id>`, episode
  `pe-<id>`, streamId = EP_BASE + id; "download" = keep in Your Episodes), shares are share links
  (with a description; one item per link), accounts, internet radio (`radio_stations`, admins add),
  chat (`chat_messages`), generated avatars, `search` v1. OpenSubsonic extensions: formPost,
  songLyrics, apiKeyAuthentication (`api_keys`, sha256 only; Settings → API keys), indexBasedQueue,
  playbackReport (counts a play once at half / 4 min of real listening), sonicSimilarity (sound.py
  fingerprints; findSonicPath walks from one song's sound to the other's), transcodeOffset,
  transcoding (getTranscodeDecision/getTranscodeStream; params `<codec>-<kbps>`),
  getPodcastEpisode, topSongsByArtistId. `stream` converts live to mp3/opus/aac/flac
  (`transcode.live`) and honours timeOffset; plain AAC without an offset still uses the cached
  copies. getSimilarSongs and artist info's similar artists use the sound fingerprints when
  measured. Songs/albums carry the OpenSubsonic fields; the less common tags (MusicBrainz ids,
  composers, ISRC, labels, release type, original year, explicit, moods) are read into
  `tracks.extra` / `albums.extra` (scan v4). Jukebox and videos say no (Connect is Shelf's way).
- **What's new** (`whatsnew.json`, web `whatsnew.js`, Android `whatsnew/`): shown once after an
  update; every release needs a top entry matching `__version__` (a test enforces it).

## DJ (experimental, OFF by default — a standing decision: don't extend unless revived)

`dj.py` + `dj.js`: a radio host between songs. Voices: Kokoro (`tts_worker.py`) or Chatterbox
on GPU (`chatterbox_worker.py`); lines written by a small local LLM (`local_llm.py`). Shelved.

## Android specifics

Lock-screen controls, home-screen widget (`NowPlayingWidget.kt`), swipe-to-skip, tape/CD cover
art styles, onboarding, in-app updater (`update/` — MIUI needed a special flow, fixed in 0.7.6),
share-target for Spotify/YouTube playlist links (`ShareActivity.kt`), WebView screens for web-only
pages (`ui/web/`). Media3 quirk: `adb shell media dispatch` crashes 1.11.1 — test with the app's
own buttons. Don't install anything on the Nexus 10 (serial R32D204ZH6J); the test phone is the
Redmi 9.

## Standing decisions and conventions

- **Branding:** the app's own names are "Favourites" and "Shelf Mix"; otherwise generic
  Spotify-like labels are kept **on purpose**.
- **Writing style:** plain, user-facing language everywhere — commit messages, UI copy, release
  notes, docstrings ("the same recording under another name", not "audio-fingerprint dedup").
- **Workflow:** commit and push every change; work autonomously; **ask before releases and
  anything irreversible** — a tag push needs the owner's explicit "publish".
- **Shelved:** AI DJ (off by default), Discord activity (spec in
  `docs/superpowers/specs/2026-11-10-discord-activity-design.md`, nothing built).
- **Specs:** `docs/superpowers/specs/` holds the native-Android design and the Discord design.
- **Release steps:** bump the six version spots (`src/shelf/__init__.py`, `pyproject.toml`,
  `uv.lock`, `desktop/package.json`, `desktop/package-lock.json` ×2,
  `android/app/build.gradle.kts`), add the whatsnew entry, then
  `git tag -a vX.Y.Z -m "Shelf X.Y.Z" && git push origin vX.Y.Z`. The release publishes only
  if every build succeeds (10 assets). A manual `workflow_dispatch` run builds without
  publishing.
- **Dev quirks (this machine):** venv on local disk
  (`UV_PROJECT_ENVIRONMENT=~/.local/share/shelf/venv UV_LINK_MODE=copy uv run pytest`, full run
  ~140 s); Android builds with `JAVA_HOME=~/.local/share/android-build/jdk sh gradlew`; dev
  server on port 4533 via `run.sh`; dev library in "/var/mnt/Drive J/Recording test"; headless
  Chromium on CDP port 9333 for web checks (real `Input.dispatchMouseEvent` clicks, JS
  `.click()` can't start audio); Electron needs `env -u ELECTRON_RUN_AS_NODE`.

## Not built / open

- **Casting** (Chromecast / DLNA / Sonos): waiting on which devices the owner has.
- **iOS:** options discussed (Subsonic apps now; PWA; sideloaded .ipa; TestFlight needs the
  $99 account) — waiting on the owner's choice.
- **Phone checks pending:** podcasts, Requests, following artists and the taste-shaped Home
  have only been checked in a browser, not on the Redmi. (Playlist import and the share target
  were checked on the Redmi on 2026-11-12.)
- **Waiting on the owner:** Last.fm API key and secret; whether AcoustID auto-tagging is wanted
  and how far it may go; whether admins should be told when a request comes in.
- **Unreleased on main:** nothing yet. **1.0.3** (2026-11-13): request covers retried after slow answers (only a real 404 is remembered a week), artist photos on artist requests. **1.0.2** (2026-11-13) fixed what a code review found (measuring held up scans, ffmpeg stalls, proxy sign-in for Connect and email names). **1.0.1** (2026-11-13) shipped complete Subsonic/OpenSubsonic support (see Admin and operations), API keys in Settings,
  big-library speed and memory work, a Docker image (`Dockerfile`, `compose.yaml`, `docker/config.toml`,
  `.github/workflows/docker.yml` publishes amd64+arm64 to ghcr.io/spinjitsudoom/shelf on release tags; guide in
  docs/docker.md; ARM builds skip Essentia and use the dsp engine; ~1.2 GB, mostly Debian's ffmpeg),
  sign-in through a reverse proxy (`proxyauth.py`: `proxy_user_header` + `proxy_trusted`, believed only from the
  connecting address, noted before X-Forwarded-For is applied by `proxyauth.wrap` in `shelf.main`; new names get
  accounts; also Subsonic requests with no credentials), Subsonic music folders (`musicFolderId` on artists,
  indexes, album lists, random, by genre, search), and nosniff + referrer-policy headers on every response,
  hardening from a review: Subsonic createUser/updateUser/deleteUser/changePassword need the account's own
  password (`p=`) or the proxy, never an app password or API key (`Params.signed_in_with`); ids too big for
  SQLite are "not found" (Subsonic and a FastAPI OverflowError handler); getAvatar doesn't reveal who exists;
  tests/test_fuzz.py throws junk at every Subsonic call and the main web pages; SECURITY.md. Checked
  2026-11-12 against the OpenSubsonic OpenAPI schemas (opensubsonic/open-subsonic-api, openapi/): all 45
  read calls tried match (a throwaway jsonschema script, not in the repo), and the admin's "Measuring songs" setting (any time / only at night / never,
  `background.py`; measuring runs under a `background.Turn`, which ends a run when a scan is wanted, the scan
  interval is up, the hours end or the server stops, so scans are never held up; the rest is measured next run).
- **Scale (measured 2026-11-12 on a made-up 100,000-song library, fully "measured"):** full scan 23 s, unchanged
  rescan 2.5 s; every page under 0.6 s except the first Mixes of the day (5 s, made ahead of time in the
  background by `_warm_mixes`) and first Home of the day (1.4 s). Peak memory ~500 MB (was ~890): whole-library
  queries use `db.TRACK_COLUMNS` (every column but `fp`, the 2 KB duplicate fingerprint; tests/test_scale.py
  keeps it in step with the table). The "sounds like" matrix is kept once (`sound.library_vectors`).
  Generator and benchmark scripts were throwaway (scratchpad), not in the repo. 1.0.0 (2026-11-12) shipped Your Episodes, episode downloads, Request music on Home, tabs going back to their first page and a Back button that never goes missing.
