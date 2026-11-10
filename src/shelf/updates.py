"""New versions of Shelf: noticing them, and updating this server when an admin asks.

Every six hours the server asks GitHub for the latest release (sends nothing but the
request; turn it off with `check_updates = false`). The admin dashboard then offers an
Update button, which works one of four ways depending on how this copy was installed:

- install.sh (Linux): run the installer again as its own systemd job, so it carries on
  while it restarts this server. It fetches the release, keeps settings and the library.
- a git checkout: `git pull` (only when nothing is changed locally), refresh the Python
  libraries with uv, then restart this process in place.
- the Windows installer: download the new installer and run it silently; it closes Shelf
  Server, installs over it and starts it again.
- anything else: no button, just a link to the release.

Installing automatically (on by default for the Windows installer and install.sh, off for a git
checkout; a switch in the admin dashboard): only once nothing has played on any device for half
an hour, between 2 and 6 at night, so music is never cut off. If three days go by without such a
night (a server that's always busy at night), the next half hour of quiet will do.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from . import __version__
from .db import get_meta, session, set_meta

log = logging.getLogger("shelf.updates")

REPO = "Spinjitsudoom/shelf"
LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
INSTALL_SH = f"https://raw.githubusercontent.com/{REPO}/main/install.sh"
CHECK_EVERY = 6 * 3600
ROOT = Path(__file__).resolve().parents[2]  # the source folder (for a git checkout)
MARKER = ".installed-by-install-sh"  # install.sh leaves this in the folder it installs


def parse(version: str) -> tuple[int, ...]:
    """'v0.7.1' -> (0, 7, 1). Anything after the numbers ('-beta') is ignored."""
    out = []
    for part in version.strip().lstrip("vV").split("."):
        digits = "".join(c for c in part if c.isdigit()) if part[:1].isdigit() else ""
        if not digits:
            break
        out.append(int(digits))
    return tuple(out)


QUIET = 30 * 60  # nothing played for this long
NIGHT = range(2, 6)  # hours (server time) to install in
PATIENCE = 3 * 86400  # after this long without a quiet night, any quiet half hour
AUTO_EVERY = 10 * 60  # how often to see whether it's a good moment


def should_install(hour: int, idle: float, pending: float) -> bool:
    """Whether now is a good moment to install an update: `idle` seconds since anything played,
    the update `pending` for that long, at `hour` o'clock."""
    if idle < QUIET:
        return False
    return hour in NIGHT or pending >= PATIENCE


def newer(latest: str, current: str = __version__) -> bool:
    return parse(latest) > parse(current)


def install_kind() -> str:
    """How this copy of Shelf was installed: windows, script, git or manual."""
    if getattr(sys, "frozen", False) and os.name == "nt":
        return "windows"
    if (ROOT / MARKER).exists():
        return "script"
    if (ROOT / ".git").exists() and shutil.which("git"):
        return "git"
    return "manual"


def _get(url: str, timeout: float = 20):
    req = urllib.request.Request(url, headers={"User-Agent": f"Shelf/{__version__} (update check)",
                                               "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(req, timeout=timeout)


class Updates:
    def __init__(self, enabled: bool = True, db_path: Path | None = None, idle_since=None, restart=None):
        """`idle_since()`: when anything last played (0 if never); `restart`: re-runs this server."""
        self.enabled = enabled
        self.db_path = db_path
        self.idle_since = idle_since or (lambda: 0.0)
        self._restart = restart or restart_in_place
        self._available_since: float | None = None
        self.state: dict = {"current": __version__, "latest": None, "url": None, "notes": None,
                            "available": False, "checkedAt": None, "error": None, "updating": False,
                            "kind": install_kind()}
        self._assets: dict[str, str] = {}
        self._stop = threading.Event()
        self._lock = threading.Lock()

    # ---------- checking ----------

    def start(self) -> None:
        if self.enabled:
            threading.Thread(target=self._loop, name="shelf-updates", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        self._stop.wait(30)  # let the server settle first
        last_check = 0.0
        while not self._stop.is_set():
            if time.time() - last_check >= CHECK_EVERY:
                self.check()
                last_check = time.time()
            self.auto_step(time.time())
            self._stop.wait(AUTO_EVERY)

    # ---------- installing by itself ----------

    def auto(self) -> bool:
        """Whether updates install by themselves (see the module docstring)."""
        saved = None
        if self.db_path:
            with session(self.db_path) as conn:
                saved = get_meta(conn, "auto_update")
        return saved == "1" if saved is not None else self.state["kind"] in ("windows", "script")

    def set_auto(self, on: bool) -> None:
        if self.db_path:
            with session(self.db_path) as conn:
                set_meta(conn, "auto_update", "1" if on else "0")

    def auto_step(self, now: float) -> None:
        """Install the waiting update if updates install by themselves and it's a good moment."""
        s = self.state
        if not (s["available"] and s["kind"] != "manual" and not s["updating"]) or not self.auto():
            return
        hour = time.localtime(now).tm_hour
        idle = now - (self.idle_since() or 0.0)
        pending = now - (self._available_since or now)
        if not should_install(hour, idle, pending):
            return
        log.info("Installing Shelf %s by itself (nothing has played for %d minutes)", s["latest"], idle // 60)
        try:
            self.update(self._restart)
        except Exception:
            log.exception("Installing the update by itself failed")

    def check(self) -> dict:
        try:
            with _get(LATEST) as r:
                rel = json.loads(r.read())
            tag = rel.get("tag_name") or ""
            self._assets = {a["name"]: a["browser_download_url"] for a in rel.get("assets", [])}
            self.state.update(latest=tag.lstrip("vV"), url=rel.get("html_url"), notes=(rel.get("body") or "")[:4000],
                              available=newer(tag), checkedAt=time.time(), error=None)
            if self.state["available"] and self._available_since is None:
                self._available_since = time.time()
            elif not self.state["available"]:
                self._available_since = None
            if self.state["available"]:
                log.info("Shelf %s is available (this is %s)", tag, __version__)
        except Exception as e:  # offline, rate-limited, no releases yet: try again later
            self.state.update(checkedAt=time.time(), error=f"Couldn’t check for updates ({e})")
        return self.info()

    def info(self) -> dict:
        s = dict(self.state)
        s["canUpdate"] = s["available"] and s["kind"] != "manual" and not s["updating"]
        s["auto"] = self.auto()
        return s

    # ---------- updating ----------

    def update(self, restart) -> str:
        """Start updating. `restart` re-runs this server (for a git checkout). Returns what
        happens next, for the dashboard."""
        with self._lock:
            if self.state["updating"]:
                raise ValueError("Already updating")
            if not self.state["available"]:
                raise ValueError("Shelf is up to date")
            self.state["updating"] = True
        try:
            kind = self.state["kind"]
            if kind == "script":
                return self._update_script()
            if kind == "git":
                return self._update_git(restart)
            if kind == "windows":
                return self._update_windows()
            raise ValueError("This copy of Shelf can’t update itself; install the new version by hand")
        except Exception:
            self.state["updating"] = False
            raise

    def _update_script(self) -> str:
        cmd = f"curl -fsSL {INSTALL_SH} | bash"
        if shutil.which("systemd-run"):
            # Its own unit, so restarting shelf.service doesn't stop the installer halfway.
            subprocess.run(["systemd-run", "--user", "--collect", f"--unit=shelf-update-{int(time.time())}",
                            "bash", "-c", cmd], check=True, capture_output=True, timeout=30)
        else:
            subprocess.Popen(["bash", "-c", cmd], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "Updating. Shelf restarts by itself in a minute or two."

    def _update_git(self, restart) -> str:
        def git(*args: str) -> str:
            out = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, timeout=120)
            if out.returncode != 0:
                raise ValueError(f"git {args[0]} failed: {(out.stderr or out.stdout).strip()[:300]}")
            return out.stdout
        if git("status", "--porcelain", "--untracked-files=no").strip():
            raise ValueError("This copy has changes of its own, so it isn’t updated automatically. Commit or undo them first.")
        git("pull", "--ff-only")
        uv = shutil.which("uv")
        if uv:
            subprocess.run([uv, "sync", "--frozen", "--no-dev"], cwd=ROOT, capture_output=True, timeout=600)
        threading.Timer(1.0, restart).start()  # after this answer has gone out
        return "Updated. Shelf is restarting."

    def _update_windows(self) -> str:
        name = next((n for n in self._assets if n.startswith("Shelf-Server-Setup-") and n.endswith(".exe")), None)
        if not name:
            raise ValueError("The release has no Windows server installer")
        dest = Path(tempfile.gettempdir()) / name
        with _get(self._assets[name], timeout=600) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f)
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        subprocess.Popen([str(dest), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], creationflags=flags,
                         close_fds=True)
        return "Updating. Shelf Server closes, installs the new version and starts again in a minute."


def restart_in_place() -> None:
    """Run this server again from the start, as the same process (keeps the same PID, so a
    service manager or terminal keeps watching it). The listening socket closes on exec."""
    log.info("Restarting after the update")
    os.execv(sys.argv[0], sys.argv) if os.access(sys.argv[0], os.X_OK) else \
        os.execv(sys.executable, [sys.executable, "-m", "shelf", *sys.argv[1:]])
