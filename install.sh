#!/usr/bin/env bash
# Install (or update) the Shelf server on Linux, for the current user, and keep it running
# in the background. Run it again later to update; your settings and library are kept.
#
#   curl -fsSL https://raw.githubusercontent.com/Spinjitsudoom/shelf/main/install.sh | bash
#
# Options (after `bash -s --` when piping):  --uninstall   remove Shelf (keeps your library data)
# Environment:  SHELF_SOURCE=<folder or .tar.gz>  install from there instead of the latest release
#               SHELF_PORT=4533                    the port for a new install
set -euo pipefail

REPO="Spinjitsudoom/shelf"
APP="${XDG_DATA_HOME:-$HOME/.local/share}/shelf/app"
VENV="${XDG_DATA_HOME:-$HOME/.local/share}/shelf/venv"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/shelf"
CONFIG="$CONFIG_DIR/config.toml"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT="$UNIT_DIR/shelf.service"

say() { printf '\033[1m%s\033[0m\n' "$*"; }
fail() { printf '\033[31m%s\033[0m\n' "$*" >&2; exit 1; }
have_systemd() { command -v systemctl >/dev/null && systemctl --user show-environment >/dev/null 2>&1; }

if [ "${1:-}" = "--uninstall" ]; then
  if have_systemd; then systemctl --user disable --now shelf.service 2>/dev/null || true; fi
  rm -f "$UNIT"
  rm -rf "$APP" "$VENV"
  say "Shelf is uninstalled. Your settings ($CONFIG_DIR) and library data (~/.local/share/shelf) are still there; delete them to remove everything."
  exit 0
fi

# ---------- what Shelf needs ----------
if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then
  hint="your distribution's package manager"
  if command -v apt-get >/dev/null; then hint="sudo apt install ffmpeg"
  elif command -v dnf >/dev/null; then hint="sudo dnf install ffmpeg (from RPM Fusion), or ffmpeg-free"
  elif command -v pacman >/dev/null; then hint="sudo pacman -S ffmpeg"
  elif command -v zypper >/dev/null; then hint="sudo zypper install ffmpeg"; fi
  fail "Shelf needs ffmpeg to read and stream your music. Install it ($hint), then run this again."
fi
for tool in curl tar; do command -v "$tool" >/dev/null || fail "Shelf's installer needs $tool. Install it, then run this again."; done

UV="$(command -v uv || true)"
[ -z "$UV" ] && [ -x "$HOME/.local/bin/uv" ] && UV="$HOME/.local/bin/uv"
if [ -z "$UV" ]; then
  say "Installing uv (it sets up Shelf's Python)…"
  curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh >/dev/null
  UV="$HOME/.local/bin/uv"
  [ -x "$UV" ] || fail "Installing uv didn't work. See https://docs.astral.sh/uv/ and run this again."
fi

# ---------- Shelf itself ----------
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
if [ -n "${SHELF_SOURCE:-}" ]; then
  say "Installing Shelf from $SHELF_SOURCE…"
  if [ -d "$SHELF_SOURCE" ]; then cp -a "$SHELF_SOURCE/." "$TMP/src"
  else mkdir -p "$TMP/src" && tar -xzf "$SHELF_SOURCE" -C "$TMP/src" --strip-components=1; fi
else
  TAG="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" 2>/dev/null | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -1)"
  URL="https://github.com/$REPO/archive/refs/${TAG:+tags/$TAG}${TAG:-heads/main}.tar.gz"
  say "Downloading Shelf ${TAG:-(latest code)}…"
  mkdir -p "$TMP/src"
  curl -fsSL "$URL" | tar -xz -C "$TMP/src" --strip-components=1
fi
[ -f "$TMP/src/pyproject.toml" ] || fail "That download doesn't look like Shelf."
rm -rf "$APP" && mkdir -p "$(dirname "$APP")" && mv "$TMP/src" "$APP"

say "Setting up Shelf's Python and libraries (the first time takes a minute)…"
(cd "$APP" && UV_PROJECT_ENVIRONMENT="$VENV" UV_LINK_MODE=copy "$UV" sync --frozen --no-dev --quiet)

# ---------- settings ----------
if [ ! -f "$CONFIG" ]; then
  mkdir -p "$CONFIG_DIR"
  music="[]"
  for d in "$(xdg-user-dir MUSIC 2>/dev/null || true)" "$HOME/Music"; do
    if [ -n "$d" ] && [ -d "$d" ] && [ "$d" != "$HOME" ]; then music="['$d']"; break; fi
  done
  cat > "$CONFIG" <<EOF
# Shelf's settings. Music folders are easiest to change in Shelf: Settings, Music folders.
# Every setting is explained in $APP/config.example.toml
music_dirs = $music
port = ${SHELF_PORT:-4533}
EOF
fi
PORT="$(sed -n 's/^port *= *\([0-9]*\).*/\1/p' "$CONFIG" | head -1)"; PORT="${PORT:-4533}"

# ---------- keep it running ----------
if have_systemd; then
  mkdir -p "$UNIT_DIR"
  cat > "$UNIT" <<EOF
[Unit]
Description=Shelf music server
After=network-online.target

[Service]
Environment=SHELF_CONFIG=$CONFIG
ExecStart=$VENV/bin/shelf
WorkingDirectory=$APP
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload
  systemctl --user enable shelf.service >/dev/null 2>&1
  systemctl --user restart shelf.service
  # Keep running after logging out, and start at boot.
  loginctl enable-linger "$USER" 2>/dev/null || say "(To keep Shelf running when you're logged out: sudo loginctl enable-linger $USER)"
  started="Shelf runs in the background and starts with the computer. Logs: journalctl --user -u shelf"
else
  started="To start Shelf: SHELF_CONFIG=$CONFIG $VENV/bin/shelf"
fi

ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
say "Shelf is installed."
echo "  Open it:            http://localhost:$PORT"
[ -n "$ip" ] && echo "  On other devices:   http://$ip:$PORT"
echo "  Settings:           $CONFIG"
echo "  $started"
echo
echo "The first time you open it, Shelf asks you to make the admin account."
