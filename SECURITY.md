# Security

## Reporting a problem

If you find a way into someone's Shelf, their music or their accounts, please report it
privately: on GitHub, open the **Security** tab of this repository and choose **Report a
vulnerability**. Please don't open a public issue for it.

Say what you found, how to make it happen, and which version of Shelf. You'll get an answer,
and a fix in a new release, as soon as it can be done.

## What's supported

Only the latest release gets security fixes. The server tells its admin when there's a new one
(or, in Docker, pull the new image).

## How Shelf keeps things safe

- Passwords are kept only as scrypt hashes. Eight wrong passwords from one address lock it out
  for up to 15 minutes.
- Apps made for Subsonic sign in with an app password or an API key, never the account's own
  password. Neither can change accounts: that needs the account password.
- API keys are kept only as SHA-256 fingerprints and are shown once, when made.
- Share links open only what was shared, can run out, and are off until an admin turns them on.
- Podcast feeds and episodes are fetched only from the public internet, never from addresses
  inside your network.
- A reverse proxy's sign-in header is believed only from the proxy's own addresses.
- Shelf never sends your music anywhere. What it does look up online (lyrics, artist details,
  music videos, podcasts, new releases) can be turned off in config.toml.

For using Shelf away from home, Tailscale (see the README) or HTTPS through a reverse proxy
(see docs/docker.md) keep passwords from crossing the internet in the clear.
