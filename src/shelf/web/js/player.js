// Playback engine: queue, shuffle/repeat, stream quality, lock-screen controls, resume,
// listen history, gapless playback, crossfade, volume normalization and autoplay.
//
// Gapless: two <audio> elements take turns. While one plays, the other loads the next
// track; when the first ends, the second is already buffered and starts immediately.
// Crossfade uses the same pair, starting the next one early and fading between them.
//
// Mix (a playlist played as a DJ set) uses the pair too: transitions.js plans each handover
// from the songs' beats and outros; here the next song is started on the right beat, held in
// step with this one (its speed nudged a little either way) while they overlap, and eased
// back to its own tempo afterwards.
//
// Smart shuffle: shuffle, plus a song from the library that fits after every few.
//
// Events: "track" (current track changed), "state" (play/pause/queue/mode changed),
// "time" (progress), "played" (a listen was recorded), "blocked" (the browser refused to
// start playing without a tap).

import { offline } from "./offline.js";
import { api } from "./api.js";
import { AudioEngine } from "./audio.js";
import { LOUDNESS_TARGETS, QUALITY_TIERS, settings } from "./settings.js";
import { automation, plan as planTransition } from "./transitions.js";
import { coverUrl, shuffled, store, toast } from "./util.js";

const SMART_EVERY = 3; // smart shuffle: a suggestion after every this many songs

const SAVE_KEY = "player";

/** A short silent WAV, used to unlock the second player on iOS during a tap. */
function silentWav() {
  const samples = 2205, buf = new ArrayBuffer(44 + samples * 2), v = new DataView(buf);
  const w = (o, s) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  w(0, "RIFF"); v.setUint32(4, 36 + samples * 2, true); w(8, "WAVE"); w(12, "fmt ");
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, 44100, true); v.setUint32(28, 88200, true); v.setUint16(32, 2, true);
  v.setUint16(34, 16, true); w(36, "data"); v.setUint32(40, samples * 2, true);
  return URL.createObjectURL(new Blob([buf], { type: "audio/wav" }));
}

const onMobileData = () => {
  const c = navigator.connection;
  return !!c && (c.type === "cellular" || c.saveData);
};

export class Player extends EventTarget {
  constructor(a, b) {
    super();
    this.els = [a, b];
    this.audio = a; // the element currently playing; the other is on standby
    this.engine = new AudioEngine(this.els);
    this.queue = [];
    this.index = -1;
    this.shuffle = false; // false | true | "smart"
    this.repeat = "off"; // off | all | one
    this.original = null; // queue order before shuffling, restored on un-shuffle
    this.context = null; // { label, href } of what started playback
    this.currentQuality = null;
    this._errors = 0;
    this._lastSave = 0;
    this._armed = false; // true once the listener has pressed play this session
    this._unlocked = false;
    this._downshift = 0; // quality steps dropped by auto-adjust after stalls
    this._stalls = [];
    this._fadingOut = null; // element fading out during a crossfade
    this._autoplayLoading = false;
    this._resetListen();

    const vol = store.get("volume", 1);
    for (const el of this.els) {
      el.volume = vol;
      const mine = (fn) => (e) => { if (e.target === this.audio) fn(e); };
      el.addEventListener("play", mine(() => this._emit("state")));
      el.addEventListener("pause", mine(() => { this._emit("state"); this._save(true); }));
      el.addEventListener("ended", mine(() => this._onEnded()));
      el.addEventListener("error", (e) => (e.target === this.audio ? this._onError() : this._clear(e.target)));
      el.addEventListener("playing", mine(() => { this._errors = 0; this._started = true; }));
      el.addEventListener("waiting", mine(() => { this._onStall(); this._emit("state"); }));
      el.addEventListener("timeupdate", mine(() => this._onTime()));
      el.addEventListener("durationchange", mine(() => this._emit("time")));
      el.addEventListener("canplay", mine(() => this._emit("state")));
    }
    settings.onChange((patch) => this._settingsChanged(patch));
    this._setupMediaSession();
    this._restore();
  }

  get standby() { return this.els[0] === this.audio ? this.els[1] : this.els[0]; }
  get current() { return this.queue[this.index] ?? null; }
  get playing() { return !this.audio.paused && !this.audio.ended; }
  get upNext() { return this.queue.slice(this.index + 1); }
  get nextTrack() { const i = this._nextIndex(); return i >= 0 ? this.queue[i] : null; }
  get position() { return this.audio.currentTime || 0; }
  get volume() { return this.audio.volume; }
  /** The volume as set (not ducked under the DJ). */
  get userVolume() { return store.get("volume", 1); }

  // ---- starting playback ----

  /** Play `tracks` from `start`; `startAt` begins partway into that song (the transition preview). */
  playList(tracks, start = 0, { shuffle = false, context = null, startAt = 0 } = {}) {
    if (!tracks.length) return;
    this.context = context;
    if (shuffle) {
      const first = start > 0 ? tracks[start] : null;
      const rest = shuffled(first ? tracks.filter((_, i) => i !== start) : tracks);
      this.queue = first ? [first, ...rest] : rest;
      this.original = tracks.slice();
      const smart = this.shuffle === "smart" || shuffle === "smart";
      this.shuffle = smart ? "smart" : true;
      this._go(0);
      if (smart) this._addSuggestions();
    } else {
      this.queue = tracks.slice();
      this.original = null;
      this.shuffle = false;
      this._go(start, startAt);
    }
  }

  playNext(tracks, { quiet = false } = {}) {
    if (!this.current) return this.playList(tracks);
    this.queue.splice(this.index + 1, 0, ...tracks);
    this.original?.push(...tracks);
    this._queueChanged();
    if (!quiet) toast(tracks.length === 1 ? `“${tracks[0].title}” plays next` : `${tracks.length} songs play next`);
  }

  addToQueue(tracks, { quiet = false } = {}) {
    if (!this.current) return this.playList(tracks);
    this.queue.push(...tracks);
    this.original?.push(...tracks);
    this._queueChanged();
    if (!quiet) toast(tracks.length === 1 ? `Added “${tracks[0].title}” to the queue` : `Added ${tracks.length} songs to the queue`);
  }

  jumpTo(i) {
    if (i >= 0 && i < this.queue.length) this._go(i);
  }

  removeAt(i) {
    if (i <= this.index || i >= this.queue.length) return;
    const [t] = this.queue.splice(i, 1);
    if (this.original) {
      const j = this.original.indexOf(t);
      if (j >= 0) this.original.splice(j, 1);
    }
    this._queueChanged();
  }

  /** Move a song that's still to come; it stays among the songs to come (as the phone's queue drags it). */
  moveItem(from, to) {
    if (!Number.isInteger(from) || !Number.isInteger(to) || from <= this.index || from >= this.queue.length) return;
    to = Math.min(Math.max(to, this.index + 1), this.queue.length - 1);
    if (to === from) return;
    const [t] = this.queue.splice(from, 1);
    this.queue.splice(to, 0, t);
    this._queueChanged();
  }

  clearUpNext() {
    this.queue.splice(this.index + 1);
    this.original = null;
    this._queueChanged();
  }

  /** Take over playback handed from another device: its queue, place and modes. */
  loadSnapshot({ queue, original = null, index = 0, position = 0, playing = false, shuffle = false, repeat = "off", context = null }) {
    if (!Array.isArray(queue) || !queue.length) return;
    this._finishFade();
    this.audio.pause();
    this._clear(this.standby);
    this.queue = queue;
    this.original = Array.isArray(original) ? original : null;
    this.index = Math.min(Math.max(0, index), queue.length - 1);
    this.shuffle = shuffle === "smart" ? "smart" : !!shuffle;
    this.repeat = ["off", "all", "one"].includes(repeat) ? repeat : "off";
    this.context = context;
    this.audio.preload = playing ? "auto" : "metadata";
    this._load(playing, position);
  }

  // ---- transport ----

  play() { if (this.current && this.audio.paused) this._play(); }
  pause() { this._finishFade(); this.audio.pause(); }

  toggle() {
    if (!this.current) return;
    if (this.audio.paused) this._play();
    else {
      this._finishFade();
      this.audio.pause();
    }
  }

  next() {
    const i = this.index < this.queue.length - 1 ? this.index + 1 : this.repeat === "all" ? 0 : -1;
    if (i >= 0) this._go(i);
  }

  prev() {
    if (!this.current) return;
    if (this.audio.currentTime > 3 || this.index === 0) {
      this.audio.currentTime = 0;
      return;
    }
    this._go(this.index - 1);
  }

  seek(sec) {
    if (!this.current || !Number.isFinite(sec)) return;
    this._finishFade();
    this.audio.currentTime = Math.max(0, Math.min(sec, this.duration || sec));
    this._emit("time");
  }

  get duration() {
    const d = this.audio.duration;
    return Number.isFinite(d) && d > 0 ? d : (this.current?.duration ?? 0);
  }

  setVolume(v) {
    for (const el of this.els) el.volume = v;
    store.set("volume", v);
  }

  /** Lower the music for a moment (the DJ talking), 1 = as set. Leaves the volume setting alone. */
  duck(level) {
    const v = store.get("volume", 1);
    for (const el of this.els) el.volume = Math.max(0, Math.min(1, v * level));
  }

  /** Off → shuffle → smart shuffle → off. */
  toggleShuffle() {
    const nextMode = !this.shuffle ? true : this.shuffle === true ? "smart" : false;
    if (!this.current) { this.shuffle = nextMode; this._emit("state"); return; }
    const cur = this.current;
    if (nextMode === true) {
      this.original = this.queue.slice();
      this.queue = [cur, ...shuffled(this.queue.filter((_, i) => i !== this.index))];
      this.index = 0;
      this.shuffle = true;
    } else if (nextMode === "smart") {
      this.shuffle = "smart";
      this._addSuggestions();
      toast("Smart shuffle: songs that fit are mixed in, marked with a sparkle");
    } else {
      const order = this.original ?? this.queue;
      this.queue = order.filter((t) => !t.smart || t === cur);
      this.index = Math.max(0, this.queue.indexOf(cur));
      this.original = null;
      this.shuffle = false;
    }
    this._queueChanged();
  }

  /** Smart shuffle: mix a fitting song from the library in after every few upcoming songs. */
  async _addSuggestions() {
    const upcoming = this.upNext.filter((t) => !t.smart && !t.autoplay);
    if (!upcoming.length) return;
    const want = Math.min(40, Math.ceil(upcoming.length / SMART_EVERY));
    let picks = [];
    try {
      picks = await api.suggest(this.queue.slice(0, 500).map((t) => t.id),
        { exclude: this.queue.map((t) => t.id), seed: Math.floor(Math.random() * 1e6), limit: want });
    } catch { toast("Couldn’t find songs to mix in right now"); return; }
    if (this.shuffle !== "smart" || !picks.length) return;
    const cur = this.current;
    const rest = this.upNext.filter((t) => !t.smart);
    const mixed = [];
    rest.forEach((t, i) => {
      mixed.push(t);
      if ((i + 1) % SMART_EVERY === 0 && picks.length) mixed.push({ ...picks.shift(), smart: true });
    });
    this.queue = [...this.queue.slice(0, this.index + 1), ...mixed];
    this.index = this.queue.indexOf(cur);
    this._queueChanged();
  }

  /** Keep a smart-shuffle suggestion: it becomes an ordinary song in the queue. */
  keepSuggestion(i) {
    const t = this.queue[i];
    if (t?.smart) { this.queue[i] = { ...t, smart: false }; this._queueChanged(); }
  }

  cycleRepeat() {
    this.repeat = { off: "all", all: "one", one: "off" }[this.repeat];
    this._queueChanged();
  }

  /** Turn on the sound engine if a setting needs it. Must run inside a tap/click. */
  enableEngineIfNeeded() {
    if ((!settings.needsEngine() && !this.context?.mix) || this.engine.active) return;
    this.engine.ensure();
    this.engine.resume();
    for (const el of this.els) this.engine.setFade(el, 1);
    this._applyNormalization(this.audio, this.current);
  }

  // ---- quality ----

  /** The stream tier for a track: from settings, the connection, auto-adjust and format support. */
  _qualityFor(track) {
    let q = settings.get(onMobileData() ? "cellularQuality" : "wifiQuality");
    if (q === "auto") q = onMobileData() ? "normal" : "original";
    let i = QUALITY_TIERS.indexOf(q);
    if (i < 0) i = QUALITY_TIERS.length - 1;
    i = Math.max(0, i - this._downshift);
    q = QUALITY_TIERS[i];
    if (q === "original" && track.mime && this.audio.canPlayType(track.mime) === "") q = "veryhigh";
    return q;
  }

  // A downloaded song plays from this device, online or not.
  _url(track) { return offline.url(track.id) ?? api.streamUrl(track.id, this._qualityFor(track)); }

  _onStall() {
    // Count stalls during playback (not the initial load); two in a minute means the
    // connection can't keep up, so step the quality down for the rest of the session.
    if (!this._started || !settings.get("autoAdjust") || this.audio.seeking) return;
    const now = Date.now();
    this._stalls = this._stalls.filter((t) => now - t < 60_000).concat(now);
    if (this._stalls.length >= 2 && this._downshift < QUALITY_TIERS.length - 1) {
      this._downshift++;
      this._stalls = [];
      this._clear(this.standby);
      toast("The connection is slow, so songs will stream at a lower quality for now");
    }
  }

  // ---- normalization ----

  _gainFor(track) {
    if (!settings.get("normalize") || !track) return 0;
    const albumMode = !this.shuffle && this.context?.href?.startsWith("#/album/") && track.albumLufs != null;
    const lufs = albumMode ? track.albumLufs : track.lufs;
    const peak = albumMode ? track.albumPeak : track.peak;
    if (lufs == null) return 0;
    const level = settings.get("loudness");
    let db = LOUDNESS_TARGETS[level] - lufs;
    // Normal and Quiet never push a song into clipping; Loud leans on the limiter.
    if (level !== "loud" && peak != null) db = Math.min(db, -1 - peak);
    return Math.max(-24, Math.min(12, db));
  }

  _applyNormalization(el, track) {
    if (this.engine.active) this.engine.setNormalization(el, this._gainFor(track));
  }

  // ---- internals ----

  _nextIndex() {
    if (this.repeat === "one") return -1;
    if (this.index < this.queue.length - 1) return this.index + 1;
    return this.repeat === "all" && this.queue.length ? 0 : -1;
  }

  /** Move to queue position i, handing over to the standby player if it already has that track. */
  _go(i, startAt = 0) {
    const t = this.queue[i];
    if (!t) return;
    this._finishFade();
    const sb = this.standby;
    if ((settings.get("gapless") || this._mixOn()) && sb.dataset.url === this._url(t) && !sb.error) {
      const old = this.audio;
      if (startAt > 0) try { sb.currentTime = startAt; } catch { /* not seekable yet */ }
      this.audio = sb;
      this.index = i;
      this.currentQuality = this._qualityFor(t);
      if (this.engine.active) this.engine.setFade(sb, 1);
      this._play();
      old.pause();
      this._clear(old);
      this._afterTrackChange();
      return;
    }
    this.index = i;
    this._load(true, startAt);
  }

  _load(autoplay, startAt = 0) {
    const t = this.current;
    if (!t) return;
    this.currentQuality = this._qualityFor(t);
    const url = this._url(t);
    this.audio.src = url;
    this.audio.dataset.url = url;
    this.audio.playbackRate = 1;
    if (this.engine.active) this.engine.setFade(this.audio, 1);
    if (startAt > 0) {
      this.audio.addEventListener("loadedmetadata", () => { this.audio.currentTime = startAt; }, { once: true });
    }
    if (autoplay) this._play();
    this._afterTrackChange();
  }

  _afterTrackChange() {
    this._resetListen();
    this._started = false;
    this._applyNormalization(this.audio, this.current);
    this._updateMediaSession();
    this._emit("track");
    this._emit("state");
    this._emit("time");
    this._save(true);
  }

  _queueChanged() {
    // The preloaded track may no longer be next; it's re-checked on the next timeupdate.
    this._emit("state");
    this._save(true);
  }

  _settingsChanged(patch) {
    if ("wifiQuality" in patch || "cellularQuality" in patch) {
      this._downshift = 0;
      this._clear(this.standby);
      if (this.current && this._qualityFor(this.current) !== this.currentQuality) {
        this._load(this.playing, this.audio.currentTime); // switch now, keeping our place
      }
    }
    if ("normalize" in patch || "loudness" in patch) this._applyNormalization(this.audio, this.current);
    if ("gapless" in patch && !patch.gapless) this._clear(this.standby);
    this._emit("state");
  }

  _clear(el) {
    if (el === this.audio || el === this._fadingOut) return;
    el.playbackRate = 1;
    if (!el.getAttribute("src")) return;
    el.removeAttribute("src");
    delete el.dataset.url;
    el.load();
  }

  _play() {
    this._armed = true;
    this.audio.preload = "auto";
    this.enableEngineIfNeeded();
    this.engine.resume();
    if (!this._unlocked) {
      // iOS only lets an element play without a tap if it has played during one before.
      this._unlocked = true;
      const sb = this.standby;
      if (!sb.getAttribute("src")) {
        const silent = silentWav();
        sb.src = silent;
        sb.play().then(() => sb.pause()).catch(() => {}).finally(() => {
          if (sb.getAttribute("src") === silent) this._clear(sb);
          URL.revokeObjectURL(silent);
        });
      }
    }
    const p = this.audio.play();
    if (p) p.catch((e) => {
      if (e.name === "NotAllowedError") {
        toast("Tap play to start listening");
        this._emit("blocked");
      }
    });
  }

  _preloadNext() {
    if (!settings.get("gapless") && !(settings.get("crossfade") > 0) && !this._mixOn()) return;
    if (this._fadingOut) return; // the standby player is still fading out the last song
    const t = this.nextTrack;
    const sb = this.standby;
    if (!t) {
      this._autoplayMore();
      return this._clear(sb);
    }
    const url = this._url(t);
    if (sb.dataset.url === url) return;
    sb.preload = "auto";
    sb.src = url;
    sb.dataset.url = url;
    sb.load();
    this._applyNormalization(sb, t);
  }

  /** Autoplay: when the queue is about to run out, add similar songs from the library. */
  async _autoplayMore() {
    if (!settings.get("autoplay") || this.repeat !== "off" || this._autoplayLoading || !this.current) return;
    this._autoplayLoading = true;
    try {
      const seed = this.current;
      const more = await api.similar(seed.id);
      const known = new Set(this.queue.slice(-200).map((t) => t.id));
      const fresh = more.filter((t) => !known.has(t.id)).slice(0, 25);
      if (fresh.length && this.current === seed && this.index === this.queue.length - 1) {
        this.queue.push(...fresh.map((t) => ({ ...t, autoplay: true })));
        this.original?.push(...fresh);
        this._queueChanged();
      }
    } catch { /* offline: just stop at the end */ }
    this._autoplayLoading = false;
  }

  _crossfadeSeconds(cur, nxt) {
    const cf = settings.get("crossfade");
    if (!(cf > 0) || !this.engine.active || !nxt || this._mixOn()) return 0;
    // Keep albums played in order seamless, the way they were mastered.
    const sameAlbum = !this.shuffle && cur.albumId === nxt.albumId;
    if (sameAlbum && !settings.get("crossfadeAlbums")) return 0;
    return Math.min(cf, (this.duration || 0) / 3);
  }

  _startCrossfade(seconds) {
    const i = this._nextIndex();
    const t = this.queue[i];
    const sb = this.standby;
    if (!t || sb.dataset.url !== this._url(t) || sb.error) return false;
    const old = this.audio;
    this._fadingOut = old;
    this.engine.setFade(sb, 0);
    this.audio = sb;
    this.index = i;
    this.currentQuality = this._qualityFor(t);
    this._play();
    this.engine.fadeTo(sb, 1, seconds);
    this.engine.fadeTo(old, 0, seconds);
    this._fadeTimer = setTimeout(() => this._finishFade(), seconds * 1000 + 300);
    this._afterTrackChange();
    return true;
  }

  /**
   * End a crossfade or Mix transition: the old song stops. `early` (a skip, pause or seek
   * mid-transition) brings the new one straight to full level and its own tempo.
   */
  _finishFade(early = true) {
    clearTimeout(this._fadeTimer);
    clearInterval(this._pll);
    const old = this._fadingOut;
    const mixing = this._mixing;
    this._mixing = null;
    if (!old) return;
    this._fadingOut = null;
    old.pause();
    this._clear(old);
    if (this.engine.active) {
      this.engine.resetMix(old);
      this.engine.setFade(old, 1);
      if (mixing) this.engine.resetMix(this.audio, early ? 1 : null);
    }
    if (mixing && this.audio.playbackRate !== 1) {
      if (early) this.audio.playbackRate = 1;
      else this._easeTempo(this.audio, mixing.outPeriod ? mixing.outPeriod * 8 : 4);
    }
  }

  // ---- mix ----

  _mixOn() { return !!this.context?.mix && this.engine.active && this.repeat !== "one"; }

  /** The transition from the current song into the next, planned once per pair. */
  _mixPlan() {
    const cur = this.current, nxt = this.nextTrack;
    if (!cur || !nxt) return null;
    const key = `${this.index}:${cur.id}>${nxt.id}:${JSON.stringify(cur.transition ?? "auto")}`;
    if (this._plan?.key !== key) {
      this._plan = { key, ...planTransition(cur, nxt, cur.transition ?? "auto", this.duration) };
      this._planReady = false;
    }
    return this._plan;
  }

  /** Called on every timeupdate while mixing: cue the next song, then start it on the beat. */
  _mixTick(c) {
    const p = this._mixPlan();
    if (!p || this._fadingOut || this.audio.paused) return;
    const sb = this.standby;
    const nxt = this.nextTrack;
    if (sb.dataset.url !== this._url(nxt) || sb.error) return;
    // Cue: park the next song on its first beat, at the speed it'll play at.
    if (!this._planReady && sb.readyState >= 1) {
      this._planReady = true;
      try { sb.currentTime = p.inStart; } catch { /* not seekable yet */ }
      sb.preservesPitch = true;
      sb.playbackRate = p.rate;
    }
    if (this._cueTimer || c < p.start - 0.8) return;
    // Within a second of the start: watch closely, so the first beat lands on time.
    const watch = () => {
      this._cueTimer = 0;
      if (this._plan !== p || this.audio.paused || this._fadingOut) return;
      const left = p.start - this.audio.currentTime;
      if (left > 0.004) { this._cueTimer = setTimeout(watch, Math.min(40, Math.max(1, left * 1000 - 6))); return; }
      this._startMix(p);
    };
    watch();
  }

  _startMix(p) {
    const i = this._nextIndex();
    const t = this.queue[i];
    const sb = this.standby;
    if (!t || sb.dataset.url !== this._url(t) || sb.error) return;
    if (p.length <= 0.05) { // cut: straight in
      sb.playbackRate = 1;
      try { if (Math.abs(sb.currentTime - p.inStart) > 0.05) sb.currentTime = p.inStart; } catch { /* ignore */ }
      this._go(i);
      return;
    }
    const old = this.audio;
    this._fadingOut = old;
    this._mixing = p;
    this.engine.setFade(sb, 0);
    sb.preservesPitch = true;
    sb.playbackRate = p.rate;
    try { if (Math.abs(sb.currentTime - p.inStart) > 0.08) sb.currentTime = p.inStart; } catch { /* ignore */ }
    this.audio = sb;
    this.index = i;
    this.currentQuality = this._qualityFor(t);
    this._play();
    const auto = automation(p);
    this.engine.automate(sb, auto.in);
    this.engine.automate(old, auto.out);
    if (p.beatmatch) this._lockBeats(old, sb, p);
    this._fadeTimer = setTimeout(() => this._finishFade(false), p.length * 1000 + 150);
    this._afterTrackChange();
  }

  /**
   * Keep the incoming song's beats on the outgoing song's, like a DJ riding the pitch:
   * measure how far apart they are every 50 ms and nudge its speed (at most 3%). In the
   * first moments, while it's still quiet, a bigger gap is fixed by jumping instead.
   */
  _lockBeats(out, inc, p) {
    const started = performance.now();
    let jumps = 0;
    clearInterval(this._pll);
    this._pll = setInterval(() => {
      if (this._fadingOut !== out || inc.paused || out.paused) return;
      if (inc.seeking || inc.readyState < 3) return;
      const po = (out.currentTime - p.outRef) / p.outPeriod;
      const pi = (inc.currentTime - p.inRef) / p.inPeriod;
      const err = ((((pi - po) % 1) + 1.5) % 1) - 0.5; // beats; positive: incoming is ahead
      this._beatError = err;
      if (performance.now() - started < 1500 && Math.abs(err) > 0.05 && jumps < 3) {
        jumps++;
        inc.currentTime = Math.max(0, inc.currentTime - err * p.inPeriod);
        return;
      }
      const nudge = Math.max(-0.03, Math.min(0.03, -err * p.outPeriod * 1.5));
      inc.playbackRate = p.rate * (1 + nudge);
    }, 50);
  }

  /** After a beat-matched blend, ease a song back to its own tempo over `seconds`. */
  _easeTempo(el, seconds) {
    clearInterval(this._ease);
    const from = el.playbackRate, steps = Math.max(1, Math.round(seconds * 10));
    let n = 0;
    this._ease = setInterval(() => {
      n++;
      if (el !== this.audio || n >= steps) { el.playbackRate = el === this.audio ? 1 : el.playbackRate; clearInterval(this._ease); return; }
      el.playbackRate = from + (1 - from) * (n / steps);
    }, 100);
  }

  _onEnded() {
    if (this.repeat === "one") {
      this._resetListen();
      this.audio.currentTime = 0;
      this._play();
      return;
    }
    const i = this._nextIndex();
    if (i >= 0) {
      this._go(i);
    } else if (settings.get("autoplay") && this.repeat === "off") {
      // Queue ran out before autoplay songs arrived (very short last song): fetch and go.
      this._autoplayMore().then(() => {
        if (this.index < this.queue.length - 1) this._go(this.index + 1);
        else this._emit("state");
      });
    } else {
      this._emit("state");
    }
  }

  _onError() {
    // A restored-but-unplayed track failing (e.g. signed out) shouldn't skip around.
    if (!this.current || !this.audio.getAttribute("src") || !this._armed) return;
    this._errors++;
    if (this._errors >= 3) {
      toast("Playback stopped after several songs failed. Check the server is reachable.");
      return;
    }
    toast(`Couldn’t play “${this.current.title}”. Skipping to the next song.`);
    setTimeout(() => this.next(), 1200);
  }

  _resetListen() {
    this._heard = 0;
    this._lastT = null;
    this._scrobbled = false;
  }

  _onTime() {
    this._emit("time");
    this._save(false);
    const d = this.duration, c = this.audio.currentTime;
    if (!d) return;

    // Count only time actually listened (not seeks) toward a play.
    if (this._lastT != null) {
      const delta = c - this._lastT;
      if (delta > 0 && delta < 2) this._heard += delta;
    }
    this._lastT = c;
    if (!this._scrobbled && this._heard >= Math.min(240, d / 2)) {
      this._scrobbled = true;
      if (!settings.get("privateSession")) api.played(this.current.id).then(() => this._emit("played"));
    }

    // Start loading the next song a little way in, so it's ready the moment this one ends.
    if (c > Math.min(8, d * 0.3)) this._preloadNext();

    if (this._mixOn()) this._mixTick(c);
    else {
      const fade = this._crossfadeSeconds(this.current, this.nextTrack);
      if (fade && !this._fadingOut && !this.audio.paused && d - c <= fade && d - c > 0.4) this._startCrossfade(d - c);
    }

    if ("mediaSession" in navigator && navigator.mediaSession.setPositionState) {
      try {
        navigator.mediaSession.setPositionState({ duration: d, position: Math.min(c, d), playbackRate: 1 });
      } catch { /* some browsers reject during load */ }
    }
  }

  _setupMediaSession() {
    if (!("mediaSession" in navigator)) return;
    const handlers = {
      play: () => this._play(),
      pause: () => this.audio.pause(),
      previoustrack: () => this.prev(),
      nexttrack: () => this.next(),
      seekto: (d) => this.seek(d.seekTime),
      seekbackward: (d) => this.seek(this.audio.currentTime - (d.seekOffset || 10)),
      seekforward: (d) => this.seek(this.audio.currentTime + (d.seekOffset || 10)),
    };
    for (const [action, fn] of Object.entries(handlers)) {
      try { navigator.mediaSession.setActionHandler(action, fn); } catch { /* unsupported */ }
    }
  }

  _updateMediaSession() {
    const t = this.current;
    if (!t || !("mediaSession" in navigator)) return;
    const art = t.cover
      ? [320, 640].map((s) => ({ src: new URL(coverUrl(t.albumId, t.cover, s), location.href).href, sizes: `${s}x${s}`, type: "image/webp" }))
      : [];
    navigator.mediaSession.metadata = new MediaMetadata({ title: t.title, artist: t.artist, album: t.album, artwork: art });
  }

  _save(force) {
    const now = Date.now();
    if (!force && now - this._lastSave < 5000) return;
    this._lastSave = now;
    store.set(SAVE_KEY, {
      queue: this.queue.slice(0, 2000),
      original: this.original?.slice(0, 2000) ?? null,
      index: this.index,
      time: this.audio.currentTime || 0,
      shuffle: this.shuffle,
      repeat: this.repeat,
      context: this.context,
    });
  }

  _restore() {
    const s = store.get(SAVE_KEY, null);
    if (!s || !Array.isArray(s.queue) || !s.queue.length) return;
    this.queue = s.queue;
    this.original = s.original;
    this.index = Math.min(Math.max(0, s.index), s.queue.length - 1);
    this.shuffle = s.shuffle === "smart" ? "smart" : !!s.shuffle;
    this.repeat = ["off", "all", "one"].includes(s.repeat) ? s.repeat : "off";
    this.context = s.context ?? null;
    this.audio.preload = "metadata"; // don't download the whole file until play is pressed
    this._load(false, s.time || 0);
  }

  _emit(type) { this.dispatchEvent(new Event(type)); }
}
