# Native Android, Milestone 1: phone check

Checked on 2026-11-09 on the owner's Redmi 9 (MIUI, Android 10) with Shelf Preview 0.7.0-preview.1–3. The phone was connected to the main server through its public address, over 4G.

| Check | Result |
|---|---|
| Sign in (server address, then account) | **Fail, then pass.** preview.1 crashed on the first Connect: it checked the typed address with the saved server's API, which is null before anything is saved. Fixed in preview.2 (`AppContainer.apiFor`, with a test). Then it signed in and went straight to Home. |
| Browse Home and mixes, play a mix | **Pass.** Home showed the greeting, Jump back in, the Shelf Mix tapes and Recently added; Shelf Mix 1 played, with "Playing from Shelf Mix 1". |
| Now Playing | **Pass.** The jewel case with its CD, title and artist, seek bar with times (0:00 only while a song is loading), and controls. |
| Skipping (buttons and swipe) | **Pass.** About ten songs skipped with no crash. |
| Slow starts on mobile data | **Fixed in preview.3.** Each skip took 4–12 s because on mobile data every song was requested as a 192 kbps copy, which the server converts in full before sending. Now only lossless files are converted on mobile data (`streamQuality`, with a test). Still open, on the server: converting while sending would make lossless-on-data instant too. |
| Locked screen | **Pass.** Songs carried on and moved to the next with the screen locked (including over Bluetooth, which received the song details). |
| Other apps in front | **Pass.** It kept playing on the home screen and in Messenger. |
| Swiped away from recent apps mid-song | **Pass, no gap.** The window closed and the player carried on (59 s into the song). MIUI's SwipeUpClean ran but didn't touch the player. |
| Force-closed while paused, then reopened | **Pass.** It came back on the same song, paused at the same position (102 451 ms before and after). |
| The old "Shelf" app | **Pass.** Untouched, still installed beside it. |
| Not checked this time | Cold start time, a sign-in revoked from the server, the server switched off (all covered by unit tests), and swiping at the very first or last song (covered by `SwipeToSkipTest`). |
