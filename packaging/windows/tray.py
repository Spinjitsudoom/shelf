"""Shelf Server for Windows: runs the Shelf server in the background, with an icon in the
notification area (the tray) to open Shelf, start it with Windows, or stop it.

It's the program people start ("Shelf Server.exe"). The server itself is the separate
shelf-server.exe next to it, started without a window, so the server and the ffmpeg runs it
makes never flash a console window. Settings and the library live in %LOCALAPPDATA%\\Shelf.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
import tomllib
import urllib.request
import webbrowser
import winreg
from pathlib import Path

import pystray
from PIL import Image

from shelf import updates

APP_DIR = Path(sys.executable).parent
BUNDLE = Path(getattr(sys, "_MEIPASS", APP_DIR))
DATA = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Shelf"
CONFIG = DATA / "config.toml"
LOG = DATA / "server.log"
SERVER = APP_DIR / "shelf-server.exe"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "Shelf Server"


def ensure_config() -> bool:
    """Write a starting config.toml the first time. True if this is the first run."""
    if CONFIG.exists():
        return False
    DATA.mkdir(parents=True, exist_ok=True)
    music = Path.home() / "Music"
    dirs = f"['{music}']" if music.is_dir() else "[]"  # a TOML literal string: backslashes as they are
    CONFIG.write_text(
        "# Shelf's settings. Music folders are easiest to change in Shelf: Settings, Music folders.\n"
        f"music_dirs = {dirs}\n"
        "port = 4533\n",
        encoding="utf-8",
    )
    return True


def port() -> int:
    try:
        return int(tomllib.loads(CONFIG.read_text(encoding="utf-8")).get("port", 4533))
    except (OSError, ValueError):
        return 4533


def answering(timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port()}/api/ping", timeout=timeout) as r:
            return r.status == 200
    except OSError:
        return False


def lan_address() -> str:
    """This computer's address on the local network, for phones and other computers."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # no packet is sent; it just picks the outgoing interface
            return s.getsockname()[0]
    except OSError:
        return "localhost"


def open_shelf() -> None:
    webbrowser.open(f"http://localhost:{port()}/")


# ---------- starting with Windows ----------

def autostart() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_NAME)
            return True
    except OSError:
        return False


def set_autostart(on: bool) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, f'"{sys.executable}" --background')
        else:
            try:
                winreg.DeleteValue(k, RUN_NAME)
            except OSError:
                pass


# ---------- the server ----------

class Server:
    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.quitting = False
        self.crashes = 0

    def start(self) -> None:
        env = {**os.environ, "SHELF_CONFIG": str(CONFIG),
               "PATH": f"{APP_DIR / 'ffmpeg'};{os.environ.get('PATH', '')}"}
        log = open(LOG, "ab", buffering=0)
        self.proc = subprocess.Popen([str(SERVER)], cwd=DATA, env=env, stdout=log, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        threading.Thread(target=self._watch, args=(self.proc,), daemon=True).start()

    def _watch(self, proc: subprocess.Popen) -> None:
        proc.wait()
        if self.quitting or proc is not self.proc:
            return
        # It stopped by itself: start it again, unless it keeps failing.
        self.crashes += 1
        if self.crashes <= 5:
            time.sleep(3)
            self.start()

    def stop(self) -> None:
        self.quitting = True
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def restart(self) -> None:
        self.stop()
        self.quitting = False
        self.crashes = 0
        self.start()


def self_test() -> int:
    """For the build: everything the tray needs is in the package. Exit code 0 if so."""
    Image.open(BUNDLE / "icon.png").load()
    return 0 if SERVER.exists() and (APP_DIR / "ffmpeg" / "ffmpeg.exe").exists() else 1


def main() -> None:
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    background = "--background" in sys.argv
    first = ensure_config()
    if answering():  # already running: just open it
        if not background:
            open_shelf()
        return

    server = Server()
    server.start()

    def when_ready() -> None:
        for _ in range(120):
            if answering():
                if not background:
                    open_shelf()  # the first time, Shelf asks for a name and password for the admin
                return
            time.sleep(0.5)

    threading.Thread(target=when_ready, daemon=True).start()
    if first:
        set_autostart(True)

    def quit_all(icon, _item) -> None:
        server.stop()
        icon.stop()

    # New versions: look every six hours, say so once, and offer the update in the menu.
    upd = updates.Updates()
    told: set[str] = set()

    def watch_updates() -> None:
        time.sleep(60)
        while True:
            info = upd.check()
            if info["available"] and info["latest"] not in told:
                told.add(info["latest"])
                icon.update_menu()
                try:
                    icon.notify(f"Shelf {info['latest']} is out. Choose “Update” in the Shelf Server menu.", "Shelf Server")
                except Exception:
                    pass
            time.sleep(updates.CHECK_EVERY)

    def update_now(icon, _item) -> None:
        try:
            msg = upd.update(restart=None)
        except ValueError as e:
            msg = str(e)
        try:
            icon.notify(msg, "Shelf Server")
        except Exception:
            pass

    icon = pystray.Icon(
        "shelf",
        Image.open(BUNDLE / "icon.png"),
        "Shelf Server",
        menu=pystray.Menu(
            pystray.MenuItem("Open Shelf", lambda *_: open_shelf(), default=True),
            pystray.MenuItem(lambda _i: f"On other devices: {lan_address()}:{port()}", None, enabled=False),
            pystray.MenuItem(lambda _i: f"Update to Shelf {upd.state['latest']}", update_now,
                             visible=lambda _i: upd.state["available"] and not upd.state["updating"]),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Start with Windows", lambda *_: set_autostart(not autostart()),
                             checked=lambda _i: autostart()),
            pystray.MenuItem("Open the data folder", lambda *_: os.startfile(DATA)),
            pystray.MenuItem("Restart the server", lambda *_: server.restart()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit Shelf Server", quit_all),
        ),
    )
    threading.Thread(target=watch_updates, daemon=True).start()
    icon.run()


if __name__ == "__main__":
    main()
