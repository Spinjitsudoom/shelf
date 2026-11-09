// Devices: every open Shelf can play the music, or remote-control
// the one that is.
//
// The Controller stands in for the Player everywhere in the interface. When this device
// is playing (or nothing is), it passes everything straight to the local Player. When
// another device is playing, it shows that device's state (relayed by the server) and
// turns every button press into a command for it.
//
// Events, same as the Player's: "track", "state", "time", plus "devices" when the list
// of devices or the playing one changes.

import { settings } from "./settings.js";
import { toast } from "./util.js";

const ID_KEY = "shelf-device-id";

function randomId() {
  // crypto.randomUUID needs HTTPS; getRandomValues works on plain http too.
  const bytes = crypto.getRandomValues(new Uint8Array(12));
  return "d" + [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** A per-tab id: survives reloads, but two tabs are two devices. */
function deviceId(fresh = false) {
  try {
    let id = sessionStorage.getItem(ID_KEY);
    if (!id || fresh) {
      id = randomId();
      sessionStorage.setItem(ID_KEY, id);
    }
    return id;
  } catch {
    return randomId();
  }
}

/** A sensible default name and kind for this device, from the browser. */
export function detectDevice() {
  const ua = navigator.userAgent;
  if (/SmartTV|SMART-TV|Tizen|Web0S|webOS|NetCast|BRAVIA|AFT[A-Z]|GoogleTV|Android TV|CrKey|HbbTV/i.test(ua)) {
    return { name: "TV", kind: "tv" };
  }
  const ipad = /iPad/.test(ua) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  if (/iPhone/.test(ua)) return { name: "iPhone", kind: "phone" };
  if (ipad) return { name: "iPad", kind: "tablet" };
  const browser = /Edg\//.test(ua) ? "Edge" : /OPR\//.test(ua) ? "Opera" : /SamsungBrowser/.test(ua) ? "Samsung Internet"
    : /Firefox\//.test(ua) ? "Firefox" : /Chrome\//.test(ua) ? "Chrome" : /Safari\//.test(ua) ? "Safari" : "Browser";
  if (/Android/.test(ua)) return /Mobile/.test(ua) ? { name: "Android phone", kind: "phone" } : { name: "Android tablet", kind: "tablet" };
  const os = /CrOS/.test(ua) ? "Chromebook" : /Windows/.test(ua) ? "Windows" : /Mac OS X/.test(ua) ? "Mac" : /Linux/.test(ua) ? "Linux" : "";
  return { name: os ? `${browser} on ${os}` : browser, kind: "computer" };
}

export const deviceName = () => settings.get("deviceName")?.trim() || detectDevice().name;

const MIRRORED = ["track", "state", "time"];
const HOLD_MS = 10 * 60_000; // how long a remote stays a remote without a connection

export class Controller extends EventTarget {
  constructor(local) {
    super();
    this.local = local;
    this.engine = local.engine;
    this.selfId = deviceId();
    this.devices = [];
    this.activeId = null;
    this.connected = false;
    this.remote = { state: null, queue: [], original: null, at: 0 };
    this._ws = null;
    this._retry = 0;
    this._wanted = false;
    this._wasRemote = false;
    this._sentQueueSig = "";
    this._queueRev = 0;
    this._reportTimer = 0;
    // Remote control survives a dropped connection: a phone in a pocket loses it without
    // anyone noticing. Until this time, this device still counts as the remote, and button
    // presses reconnect at once and are sent when the server answers.
    this._remoteHold = 0;
    this._pending = [];

    for (const type of MIRRORED) {
      local.addEventListener(type, () => { if (!this.remoteMode) this._emit(type); });
    }
    local.addEventListener("played", () => this._emit("played"));
    // Report changes to the other devices while this one is playing.
    local.addEventListener("state", () => this._reportSoon());
    local.addEventListener("track", () => this._reportSoon());
    for (const el of local.els) el.addEventListener("seeked", () => this._reportSoon());
    for (const el of local.els) {
      // Starting the music here makes this the playing device.
      el.addEventListener("play", () => {
        if (el === local.audio && this.connected && this.activeId !== this.selfId) this._send({ type: "claim" });
      });
    }
    local.addEventListener("blocked", () => { if (this.connected) this._send({ type: "blocked" }); });
    setInterval(() => {
      if (this.remoteMode && this.remote.state?.playing) this._emit("time");
      if (this.isActive && local.playing) this._report(false);
    }, 250);
    this._lastPeriodic = 0;

    settings.onChange((patch) => {
      if ("deviceName" in patch) this._send({ type: "rename", ...this._me() });
    });
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible" && this._wanted && !this.connected) this._connect();
    });
    addEventListener("online", () => { if (this._wanted && !this.connected) this._connect(); });
  }

  // ---- connection ----

  start() {
    this._wanted = true;
    if (!this._ws) this._connect();
  }

  stop() {
    this._wanted = false;
    this._ws?.close();
  }

  _me() {
    return { name: deviceName(), kind: detectDevice().kind };
  }

  _connect() {
    if (this._ws) return;
    const url = new URL("api/connect", location.href);
    url.protocol = location.protocol === "https:" ? "wss:" : "ws:";
    let ws;
    try { ws = new WebSocket(url); } catch { return this._retryLater(); }
    this._ws = ws;
    ws.onopen = () => ws.send(JSON.stringify({ type: "hello", id: this.selfId, ...this._me() }));
    ws.onmessage = (e) => {
      let msg;
      try { msg = JSON.parse(e.data); } catch { return; }
      this._onMessage(msg);
    };
    ws.onclose = () => {
      if (this._ws !== ws) return;
      this._ws = null;
      const was = this.connected;
      if (was && this.remoteMode) this._remoteHold = Date.now() + HOLD_MS;
      this.connected = false;
      if (was) this._modeChanged();
      this._retryLater();
    };
  }

  _retryLater() {
    if (!this._wanted) return;
    const delay = Math.min(15000, 1000 * 2 ** this._retry++);
    clearTimeout(this._retryTimer);
    this._retryTimer = setTimeout(() => {
      // In the background, only a remote keeps trying (the lock screen's buttons need it).
      if (this._wanted && !this._ws && (document.visibilityState !== "hidden" || this._holding)) this._connect();
    }, delay);
  }

  get _holding() { return !this.connected && this._remoteHold > Date.now(); }

  _send(msg) {
    if (this._ws?.readyState === WebSocket.OPEN) return this._ws.send(JSON.stringify(msg));
    // A command while the connection is down: keep it, reconnect now, send it on "welcome".
    if (msg.type === "cmd" && this._wanted) {
      this._pending.push({ msg, at: Date.now() });
      if (this._pending.length > 30) this._pending.shift();
      this._retry = 0;
      if (!this._ws) this._connect();
    }
  }

  _onMessage(msg) {
    switch (msg.type) {
      case "welcome":
        this.connected = true;
        this._retry = 0;
        this._setRemote(msg.state, msg.queue);
        this._setDevices(msg);
        this._remoteHold = 0;
        this._flushPending();
        // Already playing here (say, the server restarted): say so.
        if (this.local.playing && this.activeId !== this.selfId) this._send({ type: "claim" });
        if (this.activeId === this.selfId) this._report(true, true);
        break;
      case "devices":
        this._setDevices(msg);
        break;
      case "state":
        this._setRemote(msg.state, msg.queue);
        break;
      case "cmd":
        this._run(msg.name, msg.args || []);
        break;
      case "takeover":
        // The server marks this device as playing in the "devices" message that follows,
        // and that's when this device starts reporting its state.
        this.local.loadSnapshot(msg.snapshot);
        break;
      case "release":
        this.local.pause();
        break;
      case "duplicate":
        // A copied tab came with this tab's id: take a new one.
        this.selfId = deviceId(true);
        this._ws = null;
        this._connect();
        break;
      case "notice":
        toast(msg.text);
        break;
    }
  }

  /** Send the commands pressed while the connection was down, if there's still a device to
   * control (and they're recent: a pause from ten minutes ago is no longer wanted). */
  _flushPending() {
    const fresh = this._pending.filter((p) => Date.now() - p.at < 60_000);
    this._pending = [];
    if (this.remoteMode) for (const p of fresh) this._ws?.send(JSON.stringify(p.msg));
  }

  _setDevices({ devices, active }) {
    const wasRemote = this.remoteMode;
    const wasActive = this.isActive;
    const remotePos = wasRemote ? this.position : 0;
    this.devices = devices || [];
    this.activeId = active ?? null;
    // The playing device went away: carry on from where it was, here, paused.
    if (wasRemote && !this.remoteMode && this.activeId !== this.selfId && this.remote.queue.length) {
      const s = this.remote.state || {};
      this.local.loadSnapshot({
        queue: this.remote.queue, original: this.remote.original, index: s.index ?? 0,
        position: remotePos, playing: false, shuffle: s.shuffle, repeat: s.repeat, context: s.context,
      });
    }
    if (this.isActive && !wasActive) this._report(true, true);
    this._modeChanged();
    this._emit("devices");
  }

  _setRemote(state, queue) {
    if (queue) {
      this.remote.queue = Array.isArray(queue.tracks) ? queue.tracks : [];
      this.remote.original = queue.original ?? null;
    }
    if (state) {
      const prevTrack = this.remote.state?.track?.id;
      this.remote.state = state;
      this.remote.at = performance.now();
      if (this.remoteMode) {
        if (state.track?.id !== prevTrack) this._emit("track");
        this._emit("state");
        this._emit("time");
      }
    }
  }

  _modeChanged() {
    const remote = this.remoteMode;
    if (remote !== this._wasRemote) {
      this._wasRemote = remote;
      if (remote) this.local.pause();
    }
    for (const type of MIRRORED) this._emit(type);
  }

  // ---- reporting (when this device is playing) ----

  get isActive() { return this.connected && this.activeId === this.selfId; }

  _reportSoon() {
    if (!this.isActive) return;
    clearTimeout(this._reportTimer);
    this._reportTimer = setTimeout(() => this._report(true), 120);
  }

  _report(now, forceQueue = false) {
    if (!this.isActive) return;
    // Periodic reports keep the others' progress bars honest; every 5 s is plenty.
    const t = performance.now();
    if (!now && t - this._lastPeriodic < 5000) return;
    this._lastPeriodic = t;
    const p = this.local;
    const msg = {
      type: "state",
      state: {
        index: p.index, track: p.current, playing: p.playing, position: p.position, duration: p.duration,
        shuffle: p.shuffle, repeat: p.repeat, context: p.context, volume: p.userVolume ?? p.volume, quality: p.currentQuality,
        private: !!settings.get("privateSession"), // kept out of friend activity
      },
    };
    const sig = `${p.queue.length}:${p.queue.map((x) => x.id).join(",")}|${p.original ? p.original.length : -1}`;
    if (forceQueue || sig !== this._sentQueueSig) {
      this._sentQueueSig = sig;
      msg.queue = { rev: ++this._queueRev, tracks: p.queue, original: p.original };
    }
    this._send(msg);
  }

  // ---- commands from another device ----

  _run(name, args) {
    const p = this.local;
    const fns = {
      playList: (tracks, start, opts) => p.playList(tracks, start, opts),
      playNext: (tracks) => p.playNext(tracks),
      addToQueue: (tracks) => p.addToQueue(tracks),
      jumpTo: (i) => p.jumpTo(i),
      removeAt: (i) => p.removeAt(i),
      clearUpNext: () => p.clearUpNext(),
      toggle: () => p.toggle(),
      play: () => p.play(),
      pause: () => p.pause(),
      next: () => p.next(),
      prev: () => p.prev(),
      seek: (s) => p.seek(Number(s)),
      setVolume: (v) => { p.setVolume(Math.max(0, Math.min(1, Number(v)))); this._report(true); },
      toggleShuffle: () => p.toggleShuffle(),
      cycleRepeat: () => p.cycleRepeat(),
    };
    fns[name]?.(...args);
  }

  // ---- devices ----

  /** Another device is playing, and it's connected, so the buttons here control it. */
  get remoteMode() {
    const other = !!this.activeId && this.activeId !== this.selfId && this.devices.some((d) => d.id === this.activeId);
    return other && (this.connected || this._holding);
  }
  get activeDevice() { return this.devices.find((d) => d.id === this.activeId) ?? null; }
  get self() { return this.devices.find((d) => d.id === this.selfId) ?? { id: this.selfId, ...this._me() }; }

  /** Move playback to a device (this one included). */
  transferTo(id) {
    if (!this.connected) { toast("Can’t reach the server to see your other devices"); return; }
    if (id === this.activeId) return;
    const p = this.local;
    const snapshot = p.current ? {
      queue: p.queue, original: p.original, index: p.index, position: p.position,
      playing: p.playing, shuffle: p.shuffle, repeat: p.repeat, context: p.context,
    } : null;
    this._send({ type: "transfer", to: id, snapshot });
  }

  // ---- the Player interface, local or remote ----

  get _rs() { return this.remote.state || {}; }
  get current() { return this.remoteMode ? (this.remote.queue[this._rs.index] ?? this._rs.track ?? null) : this.local.current; }
  get playing() { return this.remoteMode ? !!this._rs.playing : this.local.playing; }
  get queue() { return this.remoteMode ? this.remote.queue : this.local.queue; }
  get index() { return this.remoteMode ? (this._rs.index ?? -1) : this.local.index; }
  get upNext() { return this.queue.slice(this.index + 1); }
  get shuffle() { return this.remoteMode ? (this._rs.shuffle === "smart" ? "smart" : !!this._rs.shuffle) : this.local.shuffle; }
  get repeat() { return this.remoteMode ? (this._rs.repeat || "off") : this.local.repeat; }
  get context() { return this.remoteMode ? (this._rs.context ?? null) : this.local.context; }
  get currentQuality() { return this.remoteMode ? this._rs.quality : this.local.currentQuality; }
  get volume() { return this.remoteMode ? (this._rs.volume ?? 1) : this.local.volume; }
  get duration() { return this.remoteMode ? (this._rs.duration || this.current?.duration || 0) : this.local.duration; }
  get position() {
    if (!this.remoteMode) return this.local.position;
    const s = this._rs;
    let pos = s.position || 0;
    if (s.playing) pos += (performance.now() - this.remote.at) / 1000;
    return Math.min(pos, this.duration || pos);
  }
  get nextTrack() {
    if (!this.remoteMode) return this.local.nextTrack;
    if (this.repeat === "one") return null;
    const i = this.index;
    return i < this.queue.length - 1 ? this.queue[i + 1] : this.repeat === "all" ? this.queue[0] ?? null : null;
  }

  _cmd(name, ...args) { this._send({ type: "cmd", name, args }); }

  /** Change shown remote state right away, before the playing device confirms. */
  _optimistic(patch) {
    if (patch.position != null) this.remote.at = performance.now();
    Object.assign(this.remote.state ??= {}, patch);
    this._emit("state");
    this._emit("time");
  }

  playList(tracks, start = 0, opts = {}) { this.remoteMode ? this._cmd("playList", tracks, start, opts) : this.local.playList(tracks, start, opts); }
  playNext(tracks, opts) {
    if (!this.remoteMode) return this.local.playNext(tracks, opts);
    this._cmd("playNext", tracks);
    toast(tracks.length === 1 ? `“${tracks[0].title}” plays next` : `${tracks.length} songs play next`);
  }
  addToQueue(tracks, opts) {
    if (!this.remoteMode) return this.local.addToQueue(tracks, opts);
    this._cmd("addToQueue", tracks);
    toast(tracks.length === 1 ? `Added “${tracks[0].title}” to the queue` : `Added ${tracks.length} songs to the queue`);
  }
  jumpTo(i) { this.remoteMode ? this._cmd("jumpTo", i) : this.local.jumpTo(i); }
  removeAt(i) { this.remoteMode ? this._cmd("removeAt", i) : this.local.removeAt(i); }
  clearUpNext() { this.remoteMode ? this._cmd("clearUpNext") : this.local.clearUpNext(); }
  toggle() {
    if (!this.remoteMode) return this.local.toggle();
    this._optimistic({ playing: !this.playing, position: this.position });
    this._cmd("toggle");
  }
  pause() {
    if (!this.remoteMode) return this.local.pause();
    this._optimistic({ playing: false, position: this.position });
    this._cmd("pause");
  }
  next() { this.remoteMode ? this._cmd("next") : this.local.next(); }
  prev() { this.remoteMode ? this._cmd("prev") : this.local.prev(); }
  seek(sec) {
    if (!this.remoteMode) return this.local.seek(sec);
    if (!Number.isFinite(sec)) return;
    const s = Math.max(0, Math.min(sec, this.duration || sec));
    this._optimistic({ position: s });
    this._cmd("seek", s);
  }
  setVolume(v) {
    if (!this.remoteMode) { this.local.setVolume(v); this._reportSoon(); return; } // remotes show it too
    this.remote.state && (this.remote.state.volume = v);
    clearTimeout(this._volTimer);
    this._volTimer = setTimeout(() => this._cmd("setVolume", v), 60);
  }
  toggleShuffle() { this.remoteMode ? this._cmd("toggleShuffle") : this.local.toggleShuffle(); }
  cycleRepeat() {
    if (!this.remoteMode) return this.local.cycleRepeat();
    this._optimistic({ repeat: { off: "all", all: "one", one: "off" }[this.repeat] });
    this._cmd("cycleRepeat");
  }
  enableEngineIfNeeded() { this.local.enableEngineIfNeeded(); }

  _emit(type) { this.dispatchEvent(new Event(type)); }
}

