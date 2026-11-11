"""A secure (https) address for the server, so passwords, sign-ins and music don't cross the
internet in the clear.

Shelf itself speaks plain http. Reached from the internet at a router's address (a port
forward), everything travels unencrypted. The fix is an https address in front of it:

- Tailscale Funnel, when the server's computer runs Tailscale: one command gives it a public
  https://<computer>.<tailnet>.ts.net address with a real certificate, without opening a port
  on the router or buying a domain. The admin dashboard can run it.
- Or the admin's own address (a domain behind Caddy, nginx, Cloudflare Tunnel...).

The server tells everyone the address (in /api/session). The apps move to it by themselves
when they're on plain http from the internet, and so does the web app, carrying its sign-in
over with a one-time code. Pages opened over plain http from the internet without a sign-in
(the sign-in page) are sent there, so passwords aren't typed in the clear. At home (a private
address) nothing changes.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import urllib.request
from urllib.parse import urlsplit

from . import procs
from .db import get_meta, set_meta

log = logging.getLogger("shelf.secure")

KEY = "secure_url"
PRIVATE_SUFFIXES = (".local", ".lan", ".home", ".internal", ".home.arpa", ".ts.net")


def normalize(raw: str | None) -> str | None:
    """https://host[:port], or None if it isn't an https address at the root."""
    raw = (raw or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = "https://" + raw
    try:
        u = urlsplit(raw)
        u.port  # noqa: B018 (raises on a bad port)
    except ValueError:
        return None
    if u.scheme.lower() != "https" or not u.hostname or u.path not in ("", "/") or u.query or u.fragment:
        return None
    return f"https://{u.netloc.lower()}"


def host_of(header: str) -> str:
    """The host from a Host header: "a:4533" → "a", "[::1]:4533" → "::1"."""
    header = header.strip()
    if header.startswith("["):
        return header[1:header.find("]")] if "]" in header else header
    if header.count(":") > 1:  # a bare IPv6 address
        return header
    return header.rsplit(":", 1)[0] if ":" in header else header


def is_private(host: str) -> bool:
    """At home or on the tailnet: loopback, LAN, Tailscale's 100.64/10, bare names, .local and such."""
    host = host.strip("[]").lower().rstrip(".")
    try:
        return not ipaddress.ip_address(host).is_global
    except ValueError:
        pass
    return host == "localhost" or "." not in host or host.endswith(PRIVATE_SUFFIXES)


def redirect_for(scheme: str, host_header: str, path: str, query: str, secure_url: str | None) -> str | None:
    """Where a page asked for over plain http from the internet should go instead (None: stay)."""
    if not secure_url or scheme != "http":
        return None
    host = host_of(host_header)
    if is_private(host) or host.lower() == (urlsplit(secure_url).hostname or ""):
        return None
    return secure_url + path + (f"?{query}" if query else "")


def get_url(conn) -> str | None:
    return get_meta(conn, KEY) or None


def set_url(conn, url: str | None) -> None:
    set_meta(conn, KEY, url or "")


def reaches(url: str, timeout: float = 30) -> bool:
    """True if this Shelf answers at `url` (a new Funnel address can take a while for its certificate)."""
    try:
        with urllib.request.urlopen(f"{url}/api/ping", timeout=timeout) as r:
            return json.loads(r.read().decode()).get("app") == "shelf"
    except (OSError, ValueError):
        return False


# ---------- Tailscale ----------

def tailscale_exe() -> str | None:
    found = shutil.which("tailscale")
    if found:
        return found
    for path in (os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Tailscale", "tailscale.exe"),
                 "/Applications/Tailscale.app/Contents/MacOS/Tailscale"):
        if os.path.isfile(path):
            return path
    return None


def _run(args: list[str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, timeout=timeout, **procs.no_window())


def name_from_status(status: dict) -> str | None:
    """This computer's Tailscale name (shelf-pc.tailnet.ts.net), when Tailscale is connected."""
    if status.get("BackendState") != "Running":
        return None
    name = (status.get("Self") or {}).get("DNSName") or ""
    return name.rstrip(".") or None


def funnel_serves(config: dict, name: str, port: int) -> bool:
    """Whether Funnel publishes https://<name> and passes it to Shelf's port."""
    host = f"{name}:443"
    if not (config.get("AllowFunnel") or {}).get(host):
        return False
    proxy = ((((config.get("Web") or {}).get(host) or {}).get("Handlers") or {}).get("/") or {}).get("Proxy") or ""
    return proxy.rstrip("/").endswith(f":{port}")


def tailscale_state(port: int) -> dict:
    """{"available", "name", "funnel"} for the admin dashboard."""
    exe = tailscale_exe()
    if not exe:
        return {"available": False, "name": None, "funnel": False}
    try:
        name = name_from_status(json.loads(_run([exe, "status", "--json"], 10).stdout or b"{}"))
        funnel = bool(name) and funnel_serves(json.loads(_run([exe, "funnel", "status", "--json"], 10).stdout or b"{}"), name, port)
    except (OSError, subprocess.SubprocessError, ValueError):
        return {"available": False, "name": None, "funnel": False}
    return {"available": name is not None, "name": name, "funnel": funnel}


def start_funnel(exe: str, port: int, wait: float = 30) -> dict:
    """Runs `tailscale funnel --bg <port>`. {"ok": True, "url"}; or {"ok": False, "allow": link} when the
    tailnet's owner has to allow Funnel first (Tailscale waits for that, so it's stopped after `wait`);
    or {"ok": False, "error"}."""
    try:
        done = _run([exe, "funnel", "--bg", str(port)], wait)
        out = (done.stdout or b"").decode(errors="replace") + (done.stderr or b"").decode(errors="replace")
        code = done.returncode
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode(errors="replace") + (e.stderr or b"").decode(errors="replace")
        code = None
    except OSError as e:
        return {"ok": False, "error": str(e)}
    link = re.search(r"https://login\.tailscale\.com/\S+", out)
    if link:
        return {"ok": False, "allow": link.group(0)}
    if code != 0:
        return {"ok": False, "error": out.strip()[-400:] or "Tailscale didn’t answer."}
    try:
        name = name_from_status(json.loads(_run([exe, "status", "--json"], 10).stdout or b"{}"))
    except (OSError, subprocess.SubprocessError, ValueError):
        name = None
    if not name:
        found = re.search(r"https://([\w.-]+\.ts\.net)", out)
        name = found.group(1) if found else None
    return {"ok": True, "url": f"https://{name}"} if name else {"ok": False, "error": out.strip()[-400:]}


def stop_funnel(exe: str) -> dict:
    try:
        done = _run([exe, "funnel", "--https=443", "off"], 30)
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "error": str(e)}
    out = ((done.stdout or b"") + (done.stderr or b"")).decode(errors="replace").strip()
    return {"ok": True} if done.returncode == 0 else {"ok": False, "error": out[-400:]}


# ---------- carrying a browser's sign-in to the secure address ----------

class Handoffs:
    """One-time codes: a signed-in page on the plain address gets one, the same page on the secure
    address trades it for a sign-in there. A browser keeps sign-ins per address, so without this
    everyone would have to type their password again."""

    def __init__(self, ttl: float = 120):
        self.ttl = ttl
        self._codes: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def make(self, user_id: int, now: float | None = None) -> str:
        now = now or time.time()
        code = secrets.token_urlsafe(32)
        with self._lock:
            self._codes = {c: v for c, v in self._codes.items() if v[1] > now}
            self._codes[code] = (user_id, now + self.ttl)
        return code

    def claim(self, code: str, now: float | None = None) -> int | None:
        now = now or time.time()
        with self._lock:
            got = self._codes.pop(code, None)
        return got[0] if got and got[1] > now else None
