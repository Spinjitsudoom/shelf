// The sound engine: routes both players through Web Audio for the mixer (EQ), volume
// normalization, crossfade, Mix transitions, mono and balance.
//
//   player A ─ normalize ─ fade ─ bass ─ high-pass ─ low-pass ─┐
//                                                              ├─ bus ─ (mono) ─ balance ─ preamp ─ EQ x6 ─ limiter ─ analyser ─ out
//   player B ─ normalize ─ fade ─ bass ─ high-pass ─ low-pass ─┘
//
// The per-player bass (low shelf), high-pass and low-pass filters are only moved during a Mix
// transition (see transitions.js); otherwise they're flat.
//
// It's only switched on when one of those settings is used: once a player is routed
// through Web Audio it can't be routed back, and on iOS this can stop playback when the
// screen locks.

import { EQ_BANDS, settings } from "./settings.js";

const dbToGain = (db) => 10 ** (db / 20);

function makeFilters(ctx) {
  return EQ_BANDS.map((f) => {
    const b = ctx.createBiquadFilter();
    // Peaking bands, so the curve passes through each handle.
    b.type = "peaking";
    b.frequency.value = f;
    b.Q.value = 1;
    b.gain.value = 0;
    return b;
  });
}

export class AudioEngine {
  constructor(elements) {
    this.els = elements;
    this.ctx = null;
    this.chains = new Map(); // element -> { norm, fade }
    settings.onChange(() => this.applySettings());
  }

  get active() { return !!this.ctx; }

  /** Build the graph. Call from a tap/click so the browser lets audio start. */
  ensure() {
    if (this.ctx) return true;
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return false;
    try { if (navigator.audioSession) navigator.audioSession.type = "playback"; } catch { /* Safari only */ }
    const ctx = new AC({ latencyHint: "playback" });
    this.ctx = ctx;
    this.bus = ctx.createGain();
    this.monoNode = ctx.createGain();
    this.monoNode.channelCount = 1;
    this.monoNode.channelCountMode = "explicit";
    this.monoNode.channelInterpretation = "speakers";
    this.panner = ctx.createStereoPanner();
    this.preamp = ctx.createGain();
    this.filters = makeFilters(ctx);
    this.limiter = ctx.createDynamicsCompressor();
    this.limiter.threshold.value = -1;
    this.limiter.knee.value = 0;
    this.limiter.ratio.value = 20;
    this.limiter.attack.value = 0.002;
    this.limiter.release.value = 0.2;
    this.analyser = ctx.createAnalyser();
    this.analyser.fftSize = 4096;
    this.analyser.smoothingTimeConstant = 0.82;

    for (const el of this.els) {
      const src = ctx.createMediaElementSource(el);
      const norm = ctx.createGain();
      const fade = ctx.createGain();
      const bass = ctx.createBiquadFilter();
      bass.type = "lowshelf";
      bass.frequency.value = 220;
      bass.gain.value = 0;
      const hp = ctx.createBiquadFilter();
      hp.type = "highpass";
      hp.frequency.value = 10;
      hp.Q.value = 0.9;
      const lp = ctx.createBiquadFilter();
      lp.type = "lowpass";
      lp.frequency.value = 20000;
      lp.Q.value = 0.9;
      src.connect(norm).connect(fade).connect(bass).connect(hp).connect(lp).connect(this.bus);
      this.chains.set(el, { norm, fade, bass, hp, lp });
    }
    let node = this.panner;
    for (const n of [this.preamp, ...this.filters, this.limiter, this.analyser]) { node.connect(n); node = n; }
    this.analyser.connect(ctx.destination);
    this._mono = null;
    this.applySettings();
    return true;
  }

  resume() {
    if (this.ctx && this.ctx.state !== "running") this.ctx.resume().catch(() => {});
  }

  applySettings() {
    if (!this.ctx) return;
    const s = settings.all();
    const t = this.ctx.currentTime;
    // mono
    if (this._mono !== s.mono) {
      this._mono = s.mono;
      this.bus.disconnect();
      this.monoNode.disconnect();
      if (s.mono) this.bus.connect(this.monoNode).connect(this.panner);
      else this.bus.connect(this.panner);
    }
    this.panner.pan.setTargetAtTime(s.balance, t, 0.02);
    const gains = s.eqEnabled ? s.eqGains : [0, 0, 0, 0, 0, 0];
    this.filters.forEach((f, i) => f.gain.setTargetAtTime(gains[i], t, 0.03));
    // Leave some headroom for boosts so the limiter isn't doing all the work.
    const boost = Math.max(0, ...gains);
    this.preamp.gain.setTargetAtTime(dbToGain(-boost * 0.5), t, 0.03);
  }

  setNormalization(el, db) {
    const c = this.chains.get(el);
    if (c) c.norm.gain.setTargetAtTime(dbToGain(db), this.ctx.currentTime, 0.05);
  }

  setFade(el, value) {
    const c = this.chains.get(el);
    if (!c) return;
    c.fade.gain.cancelScheduledValues(this.ctx.currentTime);
    c.fade.gain.setValueAtTime(value, this.ctx.currentTime);
  }

  fadeTo(el, value, seconds) {
    const c = this.chains.get(el);
    if (!c) return;
    const g = c.fade.gain, now = this.ctx.currentTime;
    g.cancelScheduledValues(now);
    g.setValueAtTime(g.value, now);
    // An equal-power-ish curve sounds smoother than a straight line.
    g.setTargetAtTime(value, now, seconds / 3.5);
  }

  /**
   * Run a Mix transition's automation on one player, starting now:
   * gain: [[from s, to s, start value, end value]] (equal-power curves),
   * bass: [[at s, dB]], highpass: [[from s, to s, start Hz, end Hz]].
   */
  automate(el, { gain = [], bass = [], highpass = [], lowpass = [] } = {}) {
    const c = this.chains.get(el);
    if (!c) return;
    const now = this.ctx.currentTime;
    for (const [t0, t1, a, b] of gain) {
      const n = 64, curve = new Float32Array(n);
      for (let i = 0; i < n; i++) {
        const x = i / (n - 1);
        // equal power: cos/sin quarter waves keep the loudness steady through the blend
        curve[i] = a < b ? a + (b - a) * Math.sin(x * Math.PI / 2) : b + (a - b) * Math.cos(x * Math.PI / 2);
      }
      c.fade.gain.cancelScheduledValues(now + t0);
      c.fade.gain.setValueAtTime(a, now + t0);
      c.fade.gain.setValueCurveAtTime(curve, now + t0 + 0.001, Math.max(0.05, t1 - t0));
    }
    for (const [t, db] of bass) {
      // a few milliseconds of glide, so the swap is quick but doesn't click
      c.bass.gain.setTargetAtTime(db, now + t, 0.012);
    }
    for (const [list, node] of [[highpass, c.hp], [lowpass, c.lp]]) {
      for (const [t0, t1, f0, f1] of list) {
        node.frequency.setValueAtTime(f0, now + t0);
        node.frequency.exponentialRampToValueAtTime(f1, now + t1);
      }
    }
  }

  /** Put a player's Mix filters back to flat (and its fade to `gain`, if given). */
  resetMix(el, gain = null) {
    const c = this.chains.get(el);
    if (!c) return;
    const now = this.ctx.currentTime;
    for (const p of [c.bass.gain, c.hp.frequency, c.lp.frequency]) { p.cancelScheduledValues(now); p.setValueAtTime(p.value, now); }
    c.bass.gain.setTargetAtTime(0, now, 0.05);
    c.hp.frequency.setTargetAtTime(10, now, 0.05);
    c.lp.frequency.setTargetAtTime(20000, now, 0.05);
    if (gain != null) {
      c.fade.gain.cancelScheduledValues(now);
      c.fade.gain.setValueAtTime(c.fade.gain.value, now);
      c.fade.gain.setTargetAtTime(gain, now, 0.08);
    }
  }

  /** Spectrum in dB per analyser bin, or null when the engine isn't running. */
  spectrum() {
    if (!this.analyser) return null;
    if (!this._bins) this._bins = new Float32Array(this.analyser.frequencyBinCount);
    this.analyser.getFloatFrequencyData(this._bins);
    return { bins: this._bins, sampleRate: this.ctx.sampleRate };
  }
}

/** The EQ curve (dB at each frequency) for a set of band gains, without touching playback. */
let offline;
export function eqResponse(gains, freqs) {
  if (!offline) {
    const OAC = window.OfflineAudioContext || window.webkitOfflineAudioContext;
    const ctx = new OAC(1, 128, 48000);
    offline = { filters: makeFilters(ctx) };
  }
  const total = new Float32Array(freqs.length);
  const mag = new Float32Array(freqs.length), phase = new Float32Array(freqs.length);
  offline.filters.forEach((f, i) => {
    f.gain.value = gains[i];
    f.getFrequencyResponse(freqs, mag, phase);
    for (let k = 0; k < freqs.length; k++) total[k] += 20 * Math.log10(mag[k]);
  });
  return total;
}
