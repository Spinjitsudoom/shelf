## Which file do I need?

**The server** (where your music lives; one per household):
- **Linux:** run `curl -fsSL https://raw.githubusercontent.com/Spinjitsudoom/shelf/main/install.sh | bash`. It needs ffmpeg.
- **Windows:** `Shelf-Server-Setup-….exe`. Shelf Server sits in the notification area; the first time, Shelf opens in your browser and asks you to make the admin account. On Windows, tempo/key analysis, CD ripping and the DJ aren't available.

**The player** (to listen on a device; connects to your server):
- **Android:** `Shelf-….apk`
- **Windows:** `Shelf-Setup-….exe`
- **Linux:** `shelf_…_amd64.deb` (Debian, Ubuntu, Mint) or `Shelf-….flatpak` (any distribution: `flatpak install --user Shelf-….flatpak`)
- **Any browser:** just open your server's address.
