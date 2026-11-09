"""Devices: every open Shelf (phone, computer, TV browser) can play the music or remote-control
the one that is.

Each browser tab keeps a WebSocket open to the hub. One device at a time is *active*: it
owns playback and reports its state (track, position, queue) here, and the hub relays that
state to every other device so they can show it. Their buttons send commands, which the hub
forwards to the active device. Moving playback to another device hands it the latest state,
with the position worked out from how long ago it was reported.

Messages are JSON objects with a "type". From devices:
  hello {id, name, kind}                 first message after connecting
  rename {name, kind}
  claim                                  "I've started playing here"
  state {state, queue?}                  active device only: what's playing (queue when it changed)
  cmd {name, args}                       control the active device
  transfer {to, snapshot?}               move playback to device `to`
  blocked                                "the browser here won't play without a tap"
To devices:
  welcome {you, devices, active, state, queue}
  devices {devices, active}
  state {state, queue?, from}
  cmd {name, args}                       (to the active device)
  takeover {snapshot}                    start playing this here
  release                                another device took over; stop playing here
  duplicate                              this id is already connected; pick a new one
  notice {text}
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from fastapi import WebSocket, WebSocketDisconnect

log = logging.getLogger("shelf.connect")

ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
KINDS = {"computer", "phone", "tablet", "tv", "speaker"}
GRACE_SECONDS = 20  # how long an active device may drop off (e.g. a phone switching networks)
COMMANDS = {
    "playList", "playNext", "addToQueue", "jumpTo", "removeAt", "clearUpNext",
    "toggle", "play", "pause", "next", "prev", "seek", "setVolume", "toggleShuffle", "cycleRepeat",
}


@dataclass
class Device:
    id: str
    ws: WebSocket
    name: str = "Web browser"
    kind: str = "computer"
    since: float = field(default_factory=time.time)

    def json(self) -> dict:
        return {"id": self.id, "name": self.name, "kind": self.kind}


def _clean_name(value) -> str:
    name = re.sub(r"\s+", " ", str(value or "")).strip()[:60]
    return name or "Web browser"


def same_origin(ws: WebSocket) -> bool:
    """Reject connections opened by other websites (the browser sends their Origin)."""
    origin = ws.headers.get("origin")
    if not origin:
        return True  # not a browser
    host = urlsplit(origin).netloc.lower()
    allowed = {h.strip().lower() for h in (ws.headers.get("host"), ws.headers.get("x-forwarded-host")) if h}
    return host in allowed


class Hub:
    def __init__(self) -> None:
        self.devices: dict[str, Device] = {}
        self.active: str | None = None
        self.state: dict | None = None  # latest state from the active device
        self.state_at = 0.0  # time.monotonic() when it arrived
        self.queue: dict | None = None  # {rev, tracks, original}
        self._grace: asyncio.Task | None = None

    # ---- helpers ----

    def _devices_msg(self) -> dict:
        devs = sorted(self.devices.values(), key=lambda d: d.since)
        active = self.active if self.active in self.devices or self._grace else None
        return {"type": "devices", "devices": [d.json() for d in devs], "active": active}

    async def _send(self, dev: Device | None, msg: dict) -> None:
        if dev is None:
            return
        try:
            await dev.ws.send_json(msg)
        except Exception:
            pass  # its own loop will notice the closed socket

    async def _broadcast(self, msg: dict, skip: str | None = None) -> None:
        await asyncio.gather(*(self._send(d, msg) for d in list(self.devices.values()) if d.id != skip))

    def snapshot(self) -> dict | None:
        """The active device's playback as it is now: last report plus the time since."""
        if not self.state or not self.queue:
            return None
        s = self.state
        pos = float(s.get("position") or 0)
        if s.get("playing"):
            pos += time.monotonic() - self.state_at
            dur = float(s.get("duration") or 0)
            if dur:
                pos = min(pos, max(0.0, dur - 0.5))
        return {
            "queue": self.queue.get("tracks") or [],
            "original": self.queue.get("original"),
            "index": s.get("index", 0),
            "position": round(pos, 2),
            "playing": bool(s.get("playing")),
            "shuffle": "smart" if s.get("shuffle") == "smart" else bool(s.get("shuffle")),
            "repeat": s.get("repeat", "off"),
            "context": s.get("context"),
        }

    async def _end_grace(self, dev_id: str) -> None:
        await asyncio.sleep(GRACE_SECONDS)
        self._grace = None
        if self.active == dev_id and dev_id not in self.devices:
            self.active = None
            await self._broadcast(self._devices_msg())

    # ---- connection ----

    async def serve(self, ws: WebSocket) -> None:
        await ws.accept()
        try:
            hello = await asyncio.wait_for(ws.receive_json(), timeout=15)
        except Exception:
            await ws.close()
            return
        dev_id = str(hello.get("id", ""))
        if hello.get("type") != "hello" or not ID_RE.match(dev_id):
            await ws.close(code=1008)
            return
        if dev_id in self.devices:
            # Usually a duplicated browser tab carrying the same id.
            await ws.send_json({"type": "duplicate"})
            await ws.close()
            return

        dev = Device(dev_id, ws, _clean_name(hello.get("name")), hello.get("kind") if hello.get("kind") in KINDS else "computer")
        self.devices[dev_id] = dev
        if self.active == dev_id and self._grace:
            self._grace.cancel()
            self._grace = None
        welcome = self._devices_msg() | {"type": "welcome", "you": dev_id, "state": self.state, "queue": self.queue}
        await ws.send_json(welcome)
        await self._broadcast(self._devices_msg(), skip=dev_id)

        try:
            while True:
                msg = await ws.receive_json()
                if isinstance(msg, dict):
                    await self._handle(dev, msg)
        except (WebSocketDisconnect, RuntimeError):
            pass
        except Exception:
            log.exception("Device connection failed")
        finally:
            if self.devices.get(dev_id) is dev:
                del self.devices[dev_id]
                if self.active == dev_id:
                    self._grace = asyncio.create_task(self._end_grace(dev_id))
                await self._broadcast(self._devices_msg())

    async def _handle(self, dev: Device, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "rename":
            dev.name = _clean_name(msg.get("name"))
            if msg.get("kind") in KINDS:
                dev.kind = msg["kind"]
            await self._broadcast(self._devices_msg())

        elif kind == "claim":
            if self.active != dev.id:
                old = self.devices.get(self.active) if self.active else None
                self.active = dev.id
                if self._grace:
                    self._grace.cancel()
                    self._grace = None
                await self._send(old, {"type": "release"})
                await self._broadcast(self._devices_msg())

        elif kind == "state":
            if self.active != dev.id or not isinstance(msg.get("state"), dict):
                return
            self.state = msg["state"]
            self.state_at = time.monotonic()
            out = {"type": "state", "state": self.state, "from": dev.id}
            if isinstance(msg.get("queue"), dict):
                self.queue = msg["queue"]
                out["queue"] = self.queue
            await self._broadcast(out, skip=dev.id)

        elif kind == "cmd":
            name = msg.get("name")
            target = self.devices.get(self.active) if self.active else None
            if name not in COMMANDS:
                return
            if not target:
                await self._send(dev, {"type": "notice", "text": "That device isn’t connected right now"})
                return
            await self._send(target, {"type": "cmd", "name": name, "args": msg.get("args") or []})

        elif kind == "transfer":
            to = self.devices.get(str(msg.get("to")))
            if not to:
                await self._send(dev, {"type": "notice", "text": "That device isn’t available anymore"})
                return
            if to.id == self.active:
                return
            old_id = self.active
            snap = self.snapshot() if old_id else None
            if snap is None:
                snap = msg.get("snapshot") if isinstance(msg.get("snapshot"), dict) else None
            if snap is None:
                await self._send(dev, {"type": "notice", "text": "Play something first, then move it"})
                return
            self.active = to.id
            if self._grace:
                self._grace.cancel()
                self._grace = None
            await self._send(self.devices.get(old_id) if old_id else None, {"type": "release"})
            await self._send(to, {"type": "takeover", "snapshot": snap})
            await self._broadcast(self._devices_msg())

        elif kind == "blocked":
            await self._broadcast(
                {"type": "notice", "text": f"Tap play on {dev.name} to start the music there. Its browser needs a tap first."},
                skip=dev.id,
            )
