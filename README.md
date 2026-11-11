# Shelf

A self-hosted music server for your own CD rips, with the features of a big streaming app. It scans a folder
of music, shows it as a shelf of albums, and streams to any browser (desktop, phone or TV) and
to its own Android app, for everyone you add to it.

At a glance:

- **Your music, everywhere:** an Android app with lock-screen controls and a home-screen
  widget, plus the browser; play on any device and control it from another.
- **Accounts:** everyone gets their own Favourites, playlists, history and devices; an
  admin dashboard adds people and runs the server.
- **Made for you:** Shelf Mixes, On Repeat, Rediscover, Discover, song and artist radio,
  all matched on how songs actually sound as well as artist, genre, tempo and key.
- **Together:** shared and collaborative playlists, Friend activity and Blends.
- **Offline:** download albums, playlists and Favourites; they play with no connection.
- **DJ touches:** Smart Shuffle, beat-matched Mix transitions you can edit, lyrics, music videos,
  and (experimental, off by default) an AI radio host.
- **Getting music in:** upload from the browser, rip CDs in the server's drive, and see what
  your artists have out that you don't have yet.
- **Other apps:** a Subsonic API, so apps like Symfonium, Feishin, Substreamer and DSub play
  from Shelf too.
- **Backups:** the database (accounts, Favourites, playlists, history) is backed up every day.

The details:

- **Desktop layout:** a top bar with back/forward, Home and search; Your
  Library on the left (albums and artists, with filters, sorting, a quick filter, and a
  collapsed mode); a Now Playing panel on the right that switches to the queue; and a
  player bar with the seek bar under the controls. Phones keep the tab-bar layout.
- **Playlists.** Create one with **+** in Your Library (or the Playlists tab on phones),
  then add songs from any song or album menu, by dragging songs or albums onto it, or
  with the search on the playlist's own page. Drag songs to reorder them (or use Move
  up / Move down on touch screens). Playlists live on the server, so every device sees them.
- **Playlist columns like a DJ app:** BPM, key (in Camelot notation, colored around
  the wheel, so neighbouring numbers mix well), album and date added. Below the songs,
  **Recommended** suggests songs from your library that fit: the same artists and genres,
  similar tempos and compatible keys. **Add** puts one in; **Refresh** shows others.
- **About the artist and related music videos** in the Now Playing panel (and a
  biography on artist pages), from Wikipedia and YouTube.
- **Resizable panels.** Drag the gaps beside Your Library and the Now Playing panel.
  Drag the library narrow enough and it folds down to covers; double-click a gap to reset.
- **Music videos.** When a song has an official video on YouTube, the Now Playing panel
  (or full-screen Now Playing) offers **Switch to video**. It plays in YouTube's own
  player from where the song was, and **Switch to audio** carries on with your file from
  where the video got to. Turn the lookup off with `music_videos = false`.
- **Gapless playback.** The next song is loaded while the current one plays, so
  live albums and songs that run into each other play without a break.
- **Home** shows what you're playing, recently played and added albums, your most
  played, and albums you haven't heard in a month. A song counts as played after
  half of it (or 4 minutes), like scrobbling.
- **Quality badges** (CD quality, Hi-Res lossless, MP3 320) are read from the files.
- **Quick actions:** right-click, long-press, or the ⋯ button on any album or song.
- **Lyrics** that follow the song, lighting each line as it's sung; tap a line to jump
  there. They come from a `.lrc` file next to the song, the lyrics in the file's tags,
  or [LRCLIB](https://lrclib.net), a free lyrics database (see below).
- **Play on any device.** Every phone, computer or TV browser
  with Shelf open shows up under the devices button. Pick one and the music moves
  there, picking up at the same spot, while the device in your hand becomes the remote.
  Name each device in Settings.
- **Few outside requests, each optional.** Fonts and icons are served by Shelf itself.
  Lyrics (LRCLIB), music videos (YouTube), artist pages and new releases (Wikipedia,
  MusicBrainz, Cover Art Archive) send only artist, title and album names, and each has a
  switch in config.toml. ListenBrainz gets your listens only if you connect it.

## Install

Shelf has two halves: the **server**, on the computer with your music (one per household),
and **players** on the devices you listen on. Everything is on the
[releases page](https://github.com/Spinjitsudoom/shelf/releases/latest).

**The server**

- **Linux:** one command. It needs `ffmpeg` (`sudo apt install ffmpeg`, or your
  distribution's equivalent), sets up everything else, and keeps Shelf running in the
  background, starting with the computer. Run it again to update.

  ```bash
  curl -fsSL https://raw.githubusercontent.com/Spinjitsudoom/shelf/main/install.sh | bash
  ```

  Remove it with `… | bash -s -- --uninstall` (your library data is kept).
- **Windows:** run `Shelf-Server-Setup-….exe`. Shelf Server sits in the notification area
  (Open Shelf, Start with Windows, Quit) and has ffmpeg built in. Windows asks once whether
  to let it on the network: allow it, so your phone can reach it. Tempo and key analysis,
  "sounds like", CD ripping and the DJ aren't available on Windows.
- **From the source code** (any system with [uv](https://docs.astral.sh/uv/) and `ffmpeg`):

  ```bash
  cp config.example.toml config.toml   # optional: set music_dirs and the first admin's password
  bash run.sh
  ```

Then open http://localhost:4533. The first time, Shelf asks you to make the admin account
(unless config.toml sets a password), and you add your music folders in **Settings**. The
first scan starts straight away; after that new music is picked up every 10 minutes, or
straight away with **Admin → Rescan library**.

**Players**

- **Any browser:** open the server's address. On a phone you can add it to the home screen.
- **Android:** `Shelf-….apk`.
- **Windows:** `Shelf-Setup-….exe`.
- **Linux:** `shelf_…_amd64.deb` (Debian, Ubuntu, Mint) or `Shelf-….flatpak` for any
  distribution (`flatpak install --user Shelf-….flatpak`).

Each player asks for your server's address the first time (like `192.168.1.20:4533`), then
you sign in. The desktop players work with the keyboard's media keys and the desktop's own
playback controls.

## Updates

Everything keeps itself up to date from the [releases page](https://github.com/Spinjitsudoom/shelf/releases):

- **The server** checks every six hours. When a new version is out, the admin dashboard
  (and on Windows, the tray icon) says so, with an **Update now** button: nothing changes
  until you press it. It updates the way it was installed (the Linux install script, the
  Windows installer, or `git pull` for a copy run from the source) and restarts itself.
  `check_updates = false` in config.toml turns the check off.
- **The Android app** checks in the background, downloads the new version and shows a
  notification; tap it, and Android asks you to confirm the update.
- **The desktop players** download updates in the background. The Windows and .deb players
  install them when you close Shelf (the .deb asks for your password); the Flatpak installs
  the new bundle straight away, for the next time you open Shelf.

## Accounts

Everyone signs in with a username and password. The music is shared; each person has their
own Favourites, playlists, listening history and Connect devices.

- **The first account:** if `config.toml` has a `password`, Shelf makes an admin called
  `admin` with it (it keeps whatever likes, playlists and history were there before
  accounts). Without one, whoever opens Shelf first is asked to create the admin account.
- **Admin dashboard** (the shield in the top bar, admins only): the library at a glance,
  two weeks of listening, and **People**: add someone, set a new password, rename, make or
  remove an admin, sign someone out everywhere, or remove an account (their likes,
  playlists and history go with it). Music folders, rescans and storage are here too.
- **Sign-in lockouts:** eight wrong passwords from one address within 15 minutes lock it out
  for the rest of that time. The dashboard's **Sign-in** section lists addresses with recent
  wrong passwords and lets an admin **Unlock** one (or **Clear all**) straight away.
- **Settings → Account:** change your own password (your other devices are signed out),
  change server, sign out.
- Signing in from scripts or apps: `POST /api/login {username, password}` returns a
  `token`; send it as `Authorization: Bearer <token>`.

## Android apps

There are two, and they can be installed side by side:

- **Shelf** (`Shelf-x.y.z.apk`, about 13 MB) is the full app, described below.
- **Shelf Lite** (`Shelf-x.y.z-Lite.apk`, under 100 KB) is the lightweight version: Shelf's web
  app full screen in a small shell, with a media notification, the widget and background play.
  It's for older or low-storage phones (Android 5 and up), and it gets the web app's newest
  features first.

Shelf for Android ([android/](android/)) is a native app (Android 8 and up). On first launch it asks for the
server address (like `192.168.1.20:4533` at home, or a Tailscale name away from it), then you
sign in. **Change server** on the sign-in screen or in Settings goes back to that screen.

- **Listening:** Home, Search, Library (with Favourites and your playlists), albums, artists,
  Shelf Mixes, song and artist radio, synced lyrics, and Now Playing with swipe-to-skip and
  your choice of jewel cases or vinyl.
- **Playlists:** make them, add songs from any song's menu, reorder, rename and delete.
- **Offline:** download an album, a playlist or Favourites; with no connection, they play from
  the phone.
- **Background:** the music runs in Android's media engine, so it plays on with the screen off
  or the app swiped away. The notification, lock screen, headphone and Bluetooth buttons,
  Android Auto and a home-screen widget all control it.
- **Devices:** the phone can play for your other devices, or be a remote for one of them
  (its buttons, notification and volume keys then control that device).
- **Updates:** it checks GitHub for new releases every few hours and offers to install them
  (Settings → Check for updates does it now). Admins also get the admin dashboard in Settings.

It updates the earlier WebView app in place (same package and signing key): open it once and
sign in again. Anything downloaded in the old app needs downloading again. To keep the old,
lighter app instead, install Shelf Lite.

To build it yourself (a JDK 17+ and the Android SDK; Gradle comes with it):

```bash
cd android && ./gradlew assembleRelease            # app/build/outputs/apk/release/app-release.apk
./gradlew assembleRelease -Ppreview                # "Shelf Preview", installs beside the released app
bash android-lite/build.sh --install               # Shelf Lite (no Gradle; --install <serial> for one phone)
```

Requirements: [uv](https://docs.astral.sh/uv/) and `ffmpeg` on the PATH.

## Listening away from home

Use [Tailscale](https://tailscale.com) on the server and your devices, and don't expose the port to the internet:

```bash
sudo tailscale serve --bg 4533
```

This gives you `https://<this-machine>.<tailnet>.ts.net` on any device signed in to
your tailnet. Because it's HTTPS, the phone home-screen install and offline app
shell work too. Over plain `http://` the app still works, but those two features don't.

## Keep it running

The Linux install script and the Windows installer already do this. For a copy run from the
source code on Linux, [deploy/shelf.service](deploy/shelf.service) is a systemd user service:

```bash
mkdir -p ~/.config/systemd/user
cp deploy/shelf.service ~/.config/systemd/user/   # edit the paths if Shelf isn't in ~/shelf
systemctl --user enable --now shelf
loginctl enable-linger "$USER"   # keep running when you're logged out
```

## How it organizes music

- **Albums** are the tracks in one folder that share an album tag. `CD1`, `Disc 2` and
  similar subfolders count as one album.
- **Album artist** comes from the album-artist tag. If that's missing, it uses the
  `<Artist>/<Album>/` folder name, then the track artists. Artist names that differ
  only in capitalization are merged.
- **Covers** come from `cover.jpg` or `folder.jpg` next to the tracks, or the art
  embedded in the files.
- If a music folder is missing (an unplugged drive), its tracks are kept, not deleted.

## Settings

Shelf has a full set of listening settings, under **Settings**. Each one is saved
separately on each device.

- **Audio quality:** separate Wi-Fi and mobile-data quality: Automatic, Low (AAC 96),
  Normal (128), High (192), Very high (320) or Lossless (your files as they are), plus
  auto-adjust, which steps the quality down if the connection stalls. Browsers only
  report mobile data on Android, so iPhones always use the Wi-Fi setting.
- **Playback:** gapless playback, crossfade (0–12 s), whether to crossfade inside an
  album, Autoplay (keeps playing similar songs from your library when the queue ends),
  and mono audio.
- **Sound:** volume normalization at Loud (−11 LUFS), Normal (−14) or Quiet (−19)
  levels, and the **mixer**: a 6-band equalizer with the usual presets plus a Metal one, a curve you can
  drag, and balance. Albums played in order are normalized as a whole, so quiet and
  loud songs on them keep their relationship.
- **Privacy:** private session, and clearing the listening history.
- **Storage:** clear the converted copies made for lower quality streaming.

Normalization needs each song's loudness. Shelf reads ReplayGain or R128 tags if a
file has them, and otherwise measures the song with ffmpeg in the background after
each scan. That takes about a second per song.

The equalizer, normalization, crossfade, mono and balance run through the browser's
audio processing, which is only switched on when you use one of them. On iPhone that
processing can stop music when the screen locks, so normalization is off there by default.

## Lyrics

Shelf prefers timed lyrics (they scroll with the song) over plain ones, in this order:

1. A `.lrc` file with the same name as the song, in the same folder.
2. Lyrics stored in the file's tags.
3. LRCLIB. Shelf sends the artist, title, album and length of the song it needs, and
   saves the answer (including "not found") so each song is looked up once.

To keep everything on your server, set `online_lyrics = false` in `config.toml`.

## Tempo and key

Shelf measures each song's tempo, key, beats, intro and outro in the background after a
scan (Essentia does the listening, about 2 seconds of processor time per song, once). Settings shows the
progress. Expect the odd tempo at half or double the real one, and keys right about three
times in four, as with DJ software. Set `analyze_tempo = false` to skip it.

## Mix

Turn on **Mix** on a playlist and its songs blend into each other like a DJ set. Under
each song a pill shows how it hands over to the next: **Auto** (Shelf picks), **Blend**
(32 beats, basses swapped halfway), **Bass swap** (16 beats), **Rise** (the old song is
filtered away), **Fade** (a plain crossfade) or **Cut**. Blends start on a bar near where
the song's outro begins; the next song's tempo is adjusted (pitch kept, at most 8%) and
held on the beat while they overlap, then eased back. Songs whose tempos are too far
apart get a crossfade instead. Mix uses the beats and outros measured with the tempo, so
it works best once Settings shows that measuring is done.

Select a pill to open **Edit transition**: both songs' waveforms on one timeline (bass in
blue), with lines for what the transition does to the volume, bass and filters. Drag the
waveforms to move where it starts (a bar at a time), set its length under them, pick a
preset, or change Volume, EQ and Filter one at a time. The play button previews it on
this device; Save keeps it for that pair of songs.

## DJ (Shelf Radio): experimental, off by default

On the shelf for now: it works, but it's off until an admin turns it on in the admin dashboard
→ AI DJ → **Turn on the DJ** (and off again the same way; downloaded voices and models are kept).
While it's off there's no DJ card or buttons, and none of its AI helpers run.

The **DJ** card at the start of *Made for you* turns your music into a radio show. It plays short
sets (recent favourites, something you've never played, a throwback, an artist spotlight, deeper
cuts), and a host talks between them the way a radio DJ does:

- **Breaks** between sets, after a short jingle: back-announcing what just played ("That was War
  Pigs…"), setting up the next set, now and then a time check, a tease of what's coming, the
  station name, or a shout-out from Friend activity ("Sam's been on a Slipknot run this week").
- **Quick links** every third song inside a set.
- **Talking up to the post:** each line is written to fit the next song's intro and timed to
  finish as the vocals come in (from the beat analysis). With more to say than the intro allows,
  the host starts over the end of the song before. The music is ducked underneath, and what's
  said shows as a caption.
- **DJ** in the player (while it's on) switches to a new set; pausing pauses the host too.
- **Requests:** the microphone button next to it: type (or, where the browser can listen, say)
  "something chill", "more Slipknot" or "something I've never heard". The next set follows it,
  and the host takes the request.
- **Shaped sets:** each song gets an energy score from how it sounds; sets aim for an energy that
  suits the time of day and build up (or, late at night, wind down) with no big jumps in tempo.
  Songs inside a set blend into each other with Mix; there's a clean ending where the host talks.
- **The weekly countdown:** once a show, when there's enough history, your top five of the week,
  counted down with each number announced.
- **It learns:** songs you skip sit out for a month, themes you skip or switch away from come up
  less, and thumbs up or down on the caption tell it what you like (liked lines guide its style).
- **Two hosts:** pick a **Co-host** voice and the breaks become a quick back-and-forth.

- **The words** come from a language model, set in the admin dashboard → AI DJ. Its answers are
  held to an exact format, and any line claiming something the facts given don't back up (a year,
  "their latest album", chart talk) is replaced with a safe one:
  - **Built in:** Shelf runs a small model itself on the processor (llama.cpp with Llama 3.2
    3B, or 1B for slow machines; **Download** in the dashboard). No account, key or outside
    service; it starts when the DJ needs a line and stops after ten idle minutes. Fine on a
    four-core processor with 8 GB of memory or more; a line takes a few seconds, written ahead.
  - **Gemini** (a key from aistudio.google.com/apikey), **Claude**, or an **Ollama** server
    (this machine or another one on your network).
  - Without any, simple built-in lines are used. Sent to an outside model: each person's first
    name and the songs' titles, artists, albums and play counts.
- **Starts at once:** the opening is made while you're on Home, so the DJ talks straight away
  even when writing a line takes a while.
- **Cheap to run:** a set's break and links are written in one request (as JSON), so an hour
  of radio is about five requests. The host keeps two or three short notes per artist, written
  once from Wikipedia and reused; remembers its last few lines so it doesn't repeat itself; and
  gets the exact time spelled out ("twenty past nine in the evening") rather than working it
  out. The fixed start of every request (the host's style, with example lines) is the same each
  time, so the built-in model keeps it loaded; with Gemini, "thinking" is turned off.
- **Broadcast sound:** each line is processed like a radio voice (rumble cut, a little warmth and
  presence, compression) and evened out in loudness.
- **The voice:**
  - **Natural** (Chatterbox, on a graphics card with 4 GB or more): close to a real person, male
    voices included, with an **Expressiveness** setting. "Fenrir, natural" and the like take on a
    Kokoro voice's sound with Chatterbox's delivery. Set up from the dashboard (about 3 GB); where
    there's no suitable graphics card, Kokoro speaks instead, automatically.
  - **Light** (Kokoro, on the processor): runs anywhere. Lines are spoken sentence by sentence
    with natural pacing; Heart and Bella are its most natural voices.
  - Gemini's voices, with the Gemini key. A **Pronunciation** list fixes names it gets
  wrong ("Slipknot = Slip-not"); Yungblud, Måneskin and Ranieri are built in.
- Setting up Kokoro (once; about 350 MB):

  ```bash
  T=~/.local/share/shelf/tts && mkdir -p $T && cd $T
  uv venv --python 3.12 venv && VIRTUAL_ENV=$T/venv uv pip install kokoro-onnx soundfile
  for f in kokoro-v1.0.onnx voices-v1.0.bin; do
    curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/$f
  done
  ```

  It lives in the data folder's `tts/` (or `SHELF_TTS_DIR`) and runs on the processor.

## Made for you

Home has a **Made for you** row, worked out for each person from what they play and like:

- **Shelf Mixes** (up to six): the artists you play most, each grouped with artists in the same
  genre. About 60% is their songs (favourites and ones you haven't played much), 40% songs
  from elsewhere on the shelf that fit them by artist, genre, tempo and key. New every day at
  4 a.m. Someone with no history yet gets mixes built from the library.
- **On Repeat** (most played this past month), **Rediscover** (played a lot, not lately) and
  **Discover** (never played, picked to fit your taste, new every week), once there's enough
  history for them.
- **Radio:** "Go to song radio" in any song's menu, or **Artist radio** on an artist page:
  the song or artist, then songs from across the library that go with it. When it runs out,
  Autoplay carries on.
- **Save as playlist** keeps a mix (to edit it, or download it).

## Adding music

- **Upload** (admin dashboard → Library → **Add music**): drop songs, whole album folders or ZIP
  files, or pick them. Each song is filed as `Artist/Album/` in a music folder from its own tags;
  cover pictures go with their album; a file that's already there is skipped and nothing is
  overwritten. The library rescans when you close the window.
- **Rip a CD** (admin dashboard → CD drive, when the server has a drive and `cd-paranoia`):
  put a disc in and press **Read disc**. Shelf works out its MusicBrainz disc ID, fills in the
  artist, album, year, track titles and cover (edit them if you like, or fill them in for discs
  MusicBrainz doesn't know), then rips with cd-paranoia, which re-reads scratched spots, to FLAC
  with tags and cover, files it as `Artist/Album/NN Title.flac`, ejects the disc and rescans.
  A different drive: set `SHELF_CD_DEVICE` (default `/dev/sr0`).
- **Not on your shelf** (Home → *New from your artists*, artist pages, and `#/releases`): albums
  and EPs your artists have out that you don't have yet, from MusicBrainz, checked once a day
  (admins can press **Check now**). Covers from the Cover Art Archive; each links to MusicBrainz.
  Only artist names are sent; off with `artist_info = false`.

## Sounds like

Besides tempo and key, each song gets a fingerprint of how it sounds (tone colour, brightness,
noisiness, dynamics, danceability, busyness), measured once in the background, about 1.5
seconds a song. Recommendations, Smart Shuffle, radio, Shelf Mixes and Blends all favour songs
that sound like the ones they start from, alongside artist, genre, tempo and key.

## Sleep timer and scrobbling

- **Sleep timer:** the moon in the player bar (or on Now Playing on a phone): 5 minutes to an
  hour and a half, or the end of the song. The music fades out rather than stopping dead.
- **ListenBrainz:** Settings → Account → ListenBrainz → Connect, with your user token from
  listenbrainz.org/settings. Every song you play is sent there (artist, title, album, when),
  listens made offline included; they wait in a queue if ListenBrainz is down.

## Other music apps (Subsonic)

Shelf speaks the Subsonic API (with the OpenSubsonic additions), so apps made for Subsonic
or Navidrome work with it: Symfonium, Tempo and DSub on Android, play:Sub and Substreamer on
iPhone, Feishin and Sonixd on the desktop, and many more.

Each person turns it on in **Settings → Account → Other music apps → Set up**, which makes an
app password and shows the details to type into the app: the server address, your username
and that password. Most apps sign in with a token made from the password, which only works
with a password the server can read back, so your own password is never used for it (apps that
send the password itself can use either). **Turn off** stops every app using it.

In those apps, starring a song likes it in Shelf, playlists are your Shelf playlists, and
what you play counts as a play (and goes on to ListenBrainz or Last.fm if you've connected
them). Albums and artists can be starred too. Smaller copies are made when an app asks for a
lower bitrate.

## Chromecast

Not yet: Google's Cast library only works on https pages (and not at all inside the Android
app's web view). Serving Shelf over https (for example `tailscale serve --bg 4533`, which gives
`https://<machine>.<tailnet>.ts.net`) would make casting from Chrome possible, and also lets
browsers keep Shelf for offline use.

## Sharing with other people

- **Playlists:** the ⋯ menu on your playlist makes it **Private** (only you), **Public**
  (everyone on the server can play it and follow it into their library) or **Collaborative**
  (they can add, remove and reorder songs too; each song says who added it). Only you can
  rename, delete or change who sees it.
- **Friend activity** (the people icon in the top bar): what everyone else is playing right
  now, and on which device, or what they played last. Tap a song to play it. It refreshes
  while it's open, and lists everyone's shared playlists.
- **Blend:** a playlist for two, from Friend activity: songs you both play, each of your
  favourites, and songs that fit you both, each marked "For you", "For Sam" or "For both of
  you", with your taste match once you've both played enough. New every day.
- **Privacy:** Settings → Account → *Share what I listen to*. Off, you're not in Friend
  activity and nobody can Blend with you. Private sessions never show.

## Downloads

The download button (an arrow in a ring, next to Shuffle) on an album, a playlist or Liked
Songs saves it on this device, in the browser's storage, so it plays with no connection.
Downloaded songs get a small arrow in their row, the library has a **Downloaded** filter, and
**Downloads** lists everything with the space it takes. Settings → Downloads sets the quality
(Very high, AAC 320, by default) and can remove them all.

- Downloaded playlists and Favourites follow changes: songs you add are downloaded, songs you
  remove are deleted. A song in two downloads is stored once.
- With no connection, Shelf opens on Downloads and plays from there; album and playlist pages
  you've downloaded still open. Songs played offline go into your history when you're back,
  with the time you played them.
- In the Android app, the app itself is also kept on the phone, so it opens with no
  connection at all. In a browser, that needs https (or localhost), where the service worker
  can keep it.

## Favourites and Smart Shuffle

The heart on any song saves it to **Favourites**, pinned at the top of Your Library.
Pressing shuffle twice turns on **smart shuffle**: after every three songs it adds one
from your library that fits (same artists and genres, nearby tempos and keys), marked
with a sparkle; the check mark keeps it, and turning shuffle off takes them out again.
On a playlist, **Add** opens a side panel with suggestions, recently played songs, your
favourites and a search.

## Music folders

Add, change or remove music folders in **Admin > Library**. A folder picker lists the
server's folders (never files). Changing a folder, say after a drive is mounted somewhere
else, keeps the likes, playlists and history of songs found at the same place under the new
folder. Removing one takes its songs out of the library without touching the files. A
folder that's temporarily missing (an unplugged drive) keeps its songs until it's back.

## About the artist

Biographies and photos come from Wikipedia. Shelf sends only the artist's name, checks the
page is really about a musician or band, and keeps the photo itself, so your browser never
contacts Wikipedia. Set `artist_info = false` to turn it off.

## Music videos

Shelf asks YouTube (through yt-dlp, without downloading anything) for the song's artist
and title, and picks the artist's own upload, skipping lyric videos, covers, live
versions and audio-only uploads. The answer is saved, so each song is looked up once.
Videos play in YouTube's embedded player from youtube-nocookie.com, so YouTube's own
ads and rules apply. If lookups start failing after a YouTube change, update yt-dlp:
`uv lock --upgrade-package yt-dlp`.

## Where things live

| What | Linux (install script) | Windows | From source |
|---|---|---|---|
| Settings | `~/.config/shelf/config.toml` | `%LOCALAPPDATA%\Shelf\config.toml` | `config.toml` here (not committed) |
| Database, cover and transcode caches | `~/.local/share/shelf/` | `%LOCALAPPDATA%\Shelf\` | `~/.local/share/shelf/` |
| The program | `~/.local/share/shelf/app` | `%LOCALAPPDATA%\Programs\Shelf Server` | this folder |

Keep the database on a local disk: SQLite can corrupt on network shares.

**Backups.** Once a day Shelf copies the database into `backups/` next to it (a week of daily
copies and two months of weekly ones are kept). The admin dashboard lists them, makes one on
demand, downloads one, and moves them to another folder: a different drive is safer. **Restore**
puts one back while Shelf runs; what was there is backed up first, so it can be undone.

## Development

```bash
UV_PROJECT_ENVIRONMENT=~/.local/share/shelf/venv uv run pytest
```

The server is FastAPI (`src/shelf/`). The web app is plain HTML/CSS/JS modules
with no build step (`src/shelf/web/`).

The other pieces:

| Folder | What | Build it |
|---|---|---|
| [android/](android/) | Shelf for Android (native: Kotlin, Compose and Media3; see [the design](docs/superpowers/specs/2026-11-09-native-android-design.md)) | `cd android && ./gradlew assembleRelease` |
| [android-lite/](android-lite/) | Shelf Lite, the lightweight Android app (the web app in a small shell, no Gradle) | `bash android-lite/build.sh` |
| [desktop/](desktop/) | The Windows and Linux player (Electron) | `cd desktop && npm ci && npx electron-builder --linux deb` (or `--win nsis`) |
| [packaging/flatpak/](packaging/flatpak/) | The player as a Flatpak | see the comment at the top of the manifest |
| [packaging/windows/](packaging/windows/) | Shelf Server for Windows (PyInstaller, Inno Setup) | see [the release workflow](.github/workflows/release.yml) |
| [install.sh](install.sh) | The Linux server installer | |

GitHub Actions runs the tests (and a start-scan-stream smoke test on Linux and Windows) on
every push. Pushing a tag like `v0.7.0` (matching `__version__` in `src/shelf/__init__.py`)
builds every app and publishes them as a release.

## Licence

Shelf is free software under the [GNU Affero General Public License v3.0 or later](LICENSE):
you can use, change and share it, and if you run a changed version for other people, you
share your changes with them too. The Windows server bundles [FFmpeg](https://ffmpeg.org)
(LGPL), whose licence is in its `ffmpeg` folder.
