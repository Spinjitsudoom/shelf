# Native Android, Milestone 2: phone check

Checked on 2026-11-09 by the owner on their Redmi 9 (MIUI, Android 10), with Shelf Preview 0.7.0-preview.6, against the main server.

| Check | Result |
|---|---|
| Search | **Pass.** |
| Like and unlike | **Pass.** |
| Playlists: create, add, reorder, remove | **Pass.** |
| Song radio | **Pass.** |
| Lyrics | **Pass.** |
| Settings: theme and CD or vinyl | **Partly failed, then fixed in preview.7.** The theme worked. Vinyl changed the covers to sleeves, but Now Playing still showed a silver CD beside the sleeve. Now it shows a black record that turns at 33⅓: grooves, the gaps between songs, the album art on the label, and a reflection that stays still (`Disc`, with `DiscTest`). |
| Downloads in airplane mode | **Pass.** |
| A lossless song on mobile data starting quickly | **Pass.** The server now sends the conversion while it's being made (first bytes in 0.13 s instead of 3.8 s on this PC). |

Also fixed before the check, from the review: a song whose download failed left its album half done for good. Now opening the album or playlist again tries those songs again (`failedOrChangedDownloadsAreFetchedAgain`).

The owner then asked for the web app's tonearm (preview.8). As on the web, the record now stays in its sleeve while paused. On play, the sleeve moves left, the record slides out, and the arm swings onto it; on pause it all goes back. The vinyl deck is a little smaller than the CD one, so the arm's pivot fits on screen. `Deck` has the tests `vinylDeckHasATonearm` and `cdDeckHasNoTonearm`, and an off-screen render was checked by eye for both playing and paused.
