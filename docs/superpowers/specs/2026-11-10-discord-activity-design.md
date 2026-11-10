# Discord Activity — Design

**Status:** shelved by the owner (2026-11-10), after approval and before any building. Kept for reference.

## Intent

The owner wants their Discord profile to show what they're listening to in Shelf, as
Spotify does: "Listening to Shelf", the song, the artist, the album cover and a progress
bar. It should work whichever device they play on (phone, computer, TV browser), with no
setup on those devices.

## How it works

Discord runs on the same machine as the Shelf server (the owner's setup). The server
already knows what each person is playing on every device, through Connect: the active
device reports its state to the server, including the song, whether it's playing, the
position and the length, and whether it's a private session. So the server alone feeds
Discord. Phones and browsers need nothing new.

The server talks to the Discord desktop app over Discord's local connection:
- on Linux, a socket at `$XDG_RUNTIME_DIR/discord-ipc-0` (the builder also tries `-1` to
  `-9`, and the Flatpak and Snap locations
  `$XDG_RUNTIME_DIR/app/com.discordapp.Discord/discord-ipc-N` and
  `$XDG_RUNTIME_DIR/snap.discord/discord-ipc-N`);
- on Windows, the named pipe `\\.\pipe\discord-ipc-N`.

It does a handshake with a Discord application ID, then sets an activity of type 2
("Listening to"). No Discord account token or login is involved, and nothing goes to
Discord's servers except through the user's own Discord app.

## What Discord shows

- **Name line:** "Listening to Shelf". This is the Discord application's name.
- **Details:** the song title.
- **State:** the artist.
- **Large image:** the album cover, with the album title as its hover text. Without a
  cover, the Shelf logo is shown instead.
- **Progress bar:** start and end timestamps worked out from the reported position and
  length.

Builder's call: setting `status_display_type` so the member list reads "Listening to
<artist>" instead of "Listening to Shelf", if Discord accepts it.

## When it shows

- **Whose listening:** only the owner's. The admin dashboard picks one Shelf account,
  defaulting to the first admin account. Nobody else's listening is ever shown.
- **Playing** sets the activity.
- **Paused, stopped, or nothing played for a while:** the activity is cleared. "A while"
  means no active device, or the active device gone past Connect's 20 s grace period.
- **Private session** on the playing device clears it and keeps it clear.
- **"Share what I play"** turned off for that account clears it too. The owner already uses
  that switch to mean "keep my listening to myself".
- **Seek or skip:** updated straight away.
- **Rate limit:** Discord allows about 5 updates per 20 s. Updates are coalesced to at most
  one every 3 s, always sending the latest state. A pause or clear is never dropped.
- **Discord not running, or restarted:** the server retries the connection every 30 s
  quietly, and sets the current activity as soon as it connects. It never logs an error on
  every attempt; the admin dashboard shows the status instead.

## Album covers

Covers inside Shelf need a sign-in, and Discord can only show public https images. So
Shelf looks each album up on MusicBrainz:
1. It searches for the release group by album title and album artist.
2. It takes the best match, scored 90 or more.
3. It uses the Cover Art Archive URL
   `https://coverartarchive.org/release-group/{mbid}/front-250`.

Discord fetches that image itself.

- **The owner chose this:** real covers, knowing that album and artist names are sent to
  MusicBrainz. The new-releases feature already sends the same.
- **Caching:** the answer (an MBID or "none") is kept per album in the database, so each
  album is looked up once. "None" is retried after 30 days.
- **Rate:** MusicBrainz lookups follow the existing etiquette in `releases.py` (at most one
  request a second, the Shelf User-Agent).
- **Timing:** a lookup must never hold up the activity. The activity goes out at once with
  the Shelf logo, and is updated with the cover when the lookup finishes, if the same song
  is still playing.
- **The logo:** a public image URL in the GitHub repository,
  `https://raw.githubusercontent.com/Spinjitsudoom/shelf/main/src/shelf/web/icons/icon-512.png`,
  so no image has to be uploaded to the Discord application. The builder may use an
  uploaded asset key instead if that's simpler.

## Setup (admin dashboard)

There's a new "Discord" card on the admin dashboard. It has:
- **On/off.** Off by default, so nothing changes for anyone who doesn't turn it on.
- **Account:** whose listening to show.
- **Application ID:** pre-filled with Shelf's own application ID, so most people just turn
  it on. Anyone can paste their own ID instead (for example, to show a different name).
- **Status line:** one of "Connected to Discord"; "Discord isn't running on this
  computer"; "Discord refused the application ID"; "Off".

The settings live in the database's meta table, as the DJ settings do. Only admins can see
or change them.

## The application ID

Discord requires every Rich Presence to come from a registered Discord application, whose
name is what follows "Listening to". The owner creates one application named "Shelf" in the
Discord Developer Portal once. Its ID becomes Shelf's built-in default, so other people
running Shelf don't each have to create one. Application IDs are public, not secrets.

## Goals

- The owner's listening shows on their Discord, from any device, with real covers.
- Turning it off, a private session, or pausing makes it disappear within a few seconds.

## Non-goals

- Other accounts on the server showing on their own Discord.
- Discord running on a different computer from the server. This would need an app on each
  device, and the owner doesn't need it.
- Buttons on the Discord card ("Listen on Shelf"). Links to a private server wouldn't work
  for friends.
- Native Android or desktop-player changes. None are needed.

## Anti-goals

- Anything that needs a Discord user token, or automates the user's Discord account. That's
  against Discord's terms.
- Errors or log spam when Discord isn't running. That's the normal case on most servers.
- Any listening shown while the owner thinks it's private.

## Constraints

- **No new dependencies.** The IPC protocol is small. Each frame is a little-endian
  int32 opcode, then an int32 length, then JSON. Opcodes are 0 handshake, 1 frame, 2 close,
  3 ping, 4 pong. Use `socket.AF_UNIX` on Linux and plain file I/O on the Windows pipe.
- It runs on its own background thread or asyncio task, like the scrobbler. A slow or
  missing Discord never touches request handling.
- It's a new module, `src/shelf/discord.py`. The hook into Connect is a callback when the
  hub's state, active device or grace changes, or a light poll of `hubs`, whichever is
  simpler.
- Tests cover:
  - the frame encoding;
  - the activity built from a Connect state (title, artist, timestamps, private, paused);
  - the coalescing and rate limit;
  - the cover lookup's caching, using a fake MusicBrainz;
  - a fake Discord socket for the handshake and the clear.

## Left to the builder

- Exactly how the Connect hook is wired.
- The MusicBrainz match scoring, past "score 90 or more, album artist matches".
- The dashboard card's layout, following the existing admin cards.
- How the Windows pipe is opened.
