"""Last.fm: connecting someone's account, and the calls for scrobbling.

Last.fm wants every app to have its own API account (a key and a secret), so an admin adds the
server's in the admin dashboard (made at last.fm/api/account/create). Each person then connects
their own Last.fm account: Shelf asks Last.fm for a token, they approve it on last.fm, and Shelf
swaps the token for a session key that's kept with their account. Requests are signed with the
secret, as Last.fm's API requires: the parameters sorted by name, name and value run together,
the secret added, MD5.
"""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import __version__
from .db import get_meta, session

API = "https://ws.audioscrobbler.com/2.0/"
AUTH = "https://www.last.fm/api/auth/"
AGENT = f"Shelf/{__version__} (self-hosted music server)"


class LastfmError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def sign(params: dict, secret: str) -> str:
    text = "".join(f"{k}{params[k]}" for k in sorted(params) if k not in ("format", "callback")) + secret
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _request(params: dict, post: bool) -> dict:
    data = urllib.parse.urlencode(params).encode()
    req = (urllib.request.Request(API, data=data, headers={"User-Agent": AGENT}) if post
           else urllib.request.Request(f"{API}?{data.decode()}", headers={"User-Agent": AGENT}))
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:  # Last.fm answers errors with a JSON body too
        try:
            return json.loads(e.read() or b"{}")
        except ValueError:
            raise e from None


def call(method: str, key: str, secret: str, post: bool = False, **extra) -> dict:
    params = {"method": method, "api_key": key, **{k: str(v) for k, v in extra.items()}}
    params["api_sig"] = sign(params, secret)
    params["format"] = "json"
    r = _request(params, post)
    if "error" in r:
        raise LastfmError(int(r["error"]), r.get("message") or "Last.fm said no")
    return r


def keys(db_path: Path) -> tuple[str, str] | None:
    """The server's Last.fm API account (key, secret), if an admin has added one."""
    with session(db_path) as conn:
        key, secret = get_meta(conn, "lastfm_key"), get_meta(conn, "lastfm_secret")
    return (key, secret) if key and secret else None


def scrobble(key: str, secret: str, sk: str, listens: list[dict]) -> None:
    """Up to 50 listens: {artist, track, album, timestamp, duration}."""
    extra = {"sk": sk}
    for i, l in enumerate(listens[:50]):
        for name, value in l.items():
            if value not in (None, ""):
                extra[f"{name}[{i}]"] = value
    call("track.scrobble", key, secret, post=True, **extra)
