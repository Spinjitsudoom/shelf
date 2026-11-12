# Shelf in Docker

The Shelf server comes as a container image for ordinary PCs and servers (amd64) and for
Raspberry Pi and other ARM boards (arm64): `ghcr.io/spinjitsudoom/shelf`. It's the same server
as the Linux and Windows installs. Anything that plays from it (browsers, the Android app, the
desktop players, Subsonic apps) works the same way.

## Start it

Make a folder for Shelf, put this in it as `compose.yaml`, and change the music path to yours:

```yaml
services:
  shelf:
    image: ghcr.io/spinjitsudoom/shelf:latest
    container_name: shelf
    restart: unless-stopped
    ports:
      - "4533:4533"
    volumes:
      - ./shelf-data:/data               # accounts, library database, covers: keep this
      - /path/to/your/music:/music:ro    # your music (Shelf never changes it)
    environment:
      TZ: Europe/London                  # your time zone
```

Then run:

```bash
docker compose up -d
```

Open `http://<that computer's address>:4533`. The first person to open it makes the admin
account. Shelf starts reading `/music` straight away, and checks it for new music every 15
minutes (or immediately with **Admin → Rescan library**).

Without Compose, the same thing is:

```bash
docker run -d --name shelf --restart unless-stopped -p 4533:4533 \
  -v ./shelf-data:/data -v /path/to/your/music:/music:ro -e TZ=Europe/London \
  ghcr.io/spinjitsudoom/shelf:latest
```

## Who owns the files

Shelf runs as user 1000, not as root. Your music only needs to be readable. The `shelf-data`
folder must be writable by the user Shelf runs as. If your files belong to someone else, run
Shelf as them by adding `user: "1001:1001"` (their user and group numbers, from `id`) under
`shelf:`.

## More than one music folder

Mount each one under `/music`, then add them in **Admin → Music folders**:

```yaml
    volumes:
      - ./shelf-data:/data
      - /mnt/cds:/music/cds:ro
      - /mnt/vinyl-rips:/music/vinyl:ro
```

## Settings

Environment variables override Shelf's settings:

| Variable | What it does |
| --- | --- |
| `TZ` | Your time zone. Daily mixes, stats and "only at night" measuring go by it. |
| `SHELF_MUSIC_DIRS` | Fixed music folders, separated by `:`. This also stops them being changed in the app. |
| `SHELF_PASSWORD` | The first admin's password, instead of making the account in the browser. |
| `SHELF_ARTIST_INFO=0` | No artist pictures and biographies from Wikipedia, and no MusicBrainz lookups. |
| `SHELF_ONLINE_LYRICS=0` | Lyrics only from the files themselves, not LRCLIB. |
| `SHELF_MUSIC_VIDEOS=0` | No music videos. |
| `FORWARDED_ALLOW_IPS` | Behind a reverse proxy: see below. |
| `SHELF_PROXY_USER_HEADER`, `SHELF_PROXY_TRUSTED` | Sign in through the proxy: see below. |

## Raspberry Pi

Use a 64-bit system (Raspberry Pi OS 64-bit, or Ubuntu) on a Pi 4 or 5. A Pi 3 works, but is
slow to measure songs.

After the first scan, Shelf measures every song once: loudness for volume levelling, tempo and
key, how it sounds (for "sounds like", mixes and recommendations), and duplicates. On a Pi,
a big library keeps it busy for a while. If that gets in the way, set **Admin → Measuring
songs** to **Only at night** (1 to 7 a.m.). Songs already measured stay measured. On ARM,
Shelf uses its own measuring engine instead of Essentia (the same as on Windows).

Keep `shelf-data` on the Pi's own disk or an SSD, not on a network share: the database
doesn't like network file systems.

## Behind a reverse proxy (HTTPS)

To reach Shelf at an address like `https://music.example.com`, put it behind Caddy, nginx or
Traefik. Two things matter:

1. **Tell Shelf to trust the proxy**, so it sees each visitor's own address. Otherwise
   everyone looks like the proxy, and one person's wrong passwords lock everyone out for 15
   minutes. Set `FORWARDED_ALLOW_IPS` to the proxy's address. If the proxy runs in the same
   Compose file, set it to `"*"` and don't publish Shelf's port (remove `ports:`), so only
   the proxy can reach it.
2. **Pass websockets through.** Connect (playing on one device from another) uses
   `/api/connect`. Caddy and Traefik do this by themselves. nginx needs the `Upgrade` lines
   below.

**Caddy** (gets the certificate itself):

```
music.example.com {
    reverse_proxy shelf:4533
}
```

**nginx:**

```nginx
server {
    server_name music.example.com;
    client_max_body_size 0;            # uploads of whole albums
    location / {
        proxy_pass http://shelf:4533;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_buffering off;           # songs start playing straight away
        proxy_read_timeout 1h;
    }
    # listen 443 ssl; plus your certificate lines (certbot adds them)
}
```

**Traefik** (labels on the `shelf` service):

```yaml
    labels:
      - traefik.http.routers.shelf.rule=Host(`music.example.com`)
      - traefik.http.routers.shelf.tls.certresolver=letsencrypt
      - traefik.http.services.shelf.loadbalancer.server.port=4533
```

### Signing in through the proxy

If your proxy already signs people in (Authelia, Authentik, oauth2-proxy, Caddy's
`forward_auth`), Shelf can take its word for who's there instead of asking again. Set the
header the proxy puts the person's name in, and the proxy's addresses, the only ones Shelf
believes it from:

```yaml
    environment:
      SHELF_PROXY_USER_HEADER: Remote-User
      SHELF_PROXY_TRUSTED: 172.16.0.0/12      # Docker's own networks; or the proxy's address
```

The proxy must set that header itself on every request, replacing any copy a visitor sends
(Authelia, Authentik and Caddy's `forward_auth` do), and Shelf must only be reachable through
the proxy. Someone Shelf hasn't met gets an account of their own. Subsonic apps behind the proxy that send
no password of their own are signed in the same way. Apps that do send one (and API keys) work
as usual.

If you'd rather not open anything to the internet, Tailscale is simpler: see "Listening away
from home" in the README.

## Updating

```bash
docker compose pull && docker compose up -d
```

Your library, accounts and settings are in `shelf-data`, so they stay. In a container, Shelf
doesn't check for updates itself. Pin a version (`ghcr.io/spinjitsudoom/shelf:1.1`) if you'd
rather update when you choose.

## Backing up

Shelf keeps its own copies of its database in `shelf-data/backups` (**Admin → Backups**).
Copying the whole `shelf-data` folder while Shelf is stopped is a complete backup.
