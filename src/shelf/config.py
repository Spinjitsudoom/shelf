"""Settings, read from config.toml with environment variables taking precedence."""

from __future__ import annotations

import os
import secrets
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# Windows keeps app data under %LOCALAPPDATA%; Linux and macOS under ~/.local/share.
DEFAULT_DATA_DIR = (Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Shelf"
                    if os.name == "nt" else Path.home() / ".local" / "share" / "shelf")


@dataclass
class Config:
    music_dirs: list[Path] = field(default_factory=list)
    # Database, cover cache and transcode cache live here. Keep it on a local
    # disk: SQLite is unreliable on network shares (SMB/CIFS/NFS).
    data_dir: Path = DEFAULT_DATA_DIR
    # Empty password disables login entirely (only sensible on a trusted LAN).
    password: str = ""
    host: str = "0.0.0.0"
    port: int = 4533
    scan_interval_minutes: int = 10
    transcode_cache_mb: int = 2048
    # Look up timed lyrics on lrclib.net (sends artist, title, album and length).
    online_lyrics: bool = True
    # Look up music videos on YouTube (sends artist and title) and play them in YouTube's player.
    music_videos: bool = True
    # Show artist photos and biographies from Wikipedia (sends the artist's name).
    artist_info: bool = True
    # Measure each song's tempo and key in the background (about 2 s of CPU per song).
    analyze_tempo: bool = True
    # Ask GitHub every six hours whether a newer Shelf is out (the admin dashboard says so).
    check_updates: bool = True
    # Sign in through a reverse proxy (Authelia, Authentik...): the header it puts the person's
    # name in, and the addresses of the proxy, the only ones believed (see proxyauth.py).
    proxy_user_header: str = ""
    proxy_trusted: list[str] = field(default_factory=list)
    secret_key: str = ""

    @property
    def db_path(self) -> Path:
        return self.data_dir / "library.db"

    @property
    def cover_dir(self) -> Path:
        return self.data_dir / "covers"

    @property
    def found_cover_dir(self) -> Path:
        """Covers the admin found online for albums (coverfix.py); they win over the album's own."""
        return self.data_dir / "found-covers"

    @property
    def transcode_dir(self) -> Path:
        return self.data_dir / "transcodes"

    def prepare(self) -> "Config":
        for d in (self.data_dir, self.cover_dir, self.transcode_dir):
            d.mkdir(parents=True, exist_ok=True)
        if not self.secret_key:
            key_file = self.data_dir / "secret.key"
            if not key_file.exists():
                key_file.write_text(secrets.token_urlsafe(48))
                key_file.chmod(0o600)
            self.secret_key = key_file.read_text().strip()
        return self


def load_config(path: Path | None = None) -> Config:
    path = path or Path(os.environ.get("SHELF_CONFIG", "config.toml"))
    raw: dict = {}
    if path.exists():
        raw = tomllib.loads(path.read_text())

    env = os.environ
    cfg = Config()
    dirs = env.get("SHELF_MUSIC_DIRS")
    music_dirs = dirs.split(os.pathsep) if dirs else raw.get("music_dirs", [])
    cfg.music_dirs = [Path(d).expanduser() for d in music_dirs if d]
    cfg.data_dir = Path(env.get("SHELF_DATA_DIR") or raw.get("data_dir") or DEFAULT_DATA_DIR).expanduser()
    cfg.password = env.get("SHELF_PASSWORD", raw.get("password", ""))
    cfg.host = env.get("SHELF_HOST", raw.get("host", cfg.host))
    cfg.port = int(env.get("SHELF_PORT", raw.get("port", cfg.port)))
    cfg.scan_interval_minutes = int(raw.get("scan_interval_minutes", cfg.scan_interval_minutes))
    cfg.transcode_cache_mb = int(raw.get("transcode_cache_mb", cfg.transcode_cache_mb))
    online = env.get("SHELF_ONLINE_LYRICS")
    cfg.analyze_tempo = bool(raw.get("analyze_tempo", True))
    cfg.check_updates = bool(raw.get("check_updates", True))
    cfg.proxy_user_header = env.get("SHELF_PROXY_USER_HEADER", raw.get("proxy_user_header", ""))
    trusted = env.get("SHELF_PROXY_TRUSTED")
    cfg.proxy_trusted = [t for t in (trusted.split(",") if trusted else raw.get("proxy_trusted", [])) if str(t).strip()]
    info = env.get("SHELF_ARTIST_INFO")
    cfg.artist_info = info.lower() not in ("0", "false", "no", "off") if info else bool(raw.get("artist_info", True))
    videos = env.get("SHELF_MUSIC_VIDEOS")
    cfg.music_videos = videos.lower() not in ("0", "false", "no", "off") if videos else bool(raw.get("music_videos", True))
    cfg.online_lyrics = online.lower() not in ("0", "false", "no", "off") if online else bool(raw.get("online_lyrics", True))
    return cfg
