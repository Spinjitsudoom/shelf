// Listening settings, kept per device, with change notifications.

import { store } from "./util.js";

export const IS_IOS = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
  (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);

export const QUALITY_TIERS = ["low", "normal", "high", "veryhigh", "original"];
export const QUALITY_LABELS = {
  auto: "Automatic", low: "Low", normal: "Normal", high: "High", veryhigh: "Very high", original: "Lossless",
};
export const qualityDetail = (key, value) =>
  value === "auto"
    ? key === "wifiQuality" ? "Plays your files as they are, falling back if your browser can’t" : "AAC 128 kbps, about 1 MB a minute"
    : QUALITY_DETAIL[value];

export const QUALITY_DETAIL = {
  low: "AAC 96 kbps, about 0.7 MB a minute",
  normal: "AAC 128 kbps, about 1 MB a minute",
  high: "AAC 192 kbps, about 1.4 MB a minute",
  veryhigh: "AAC 320 kbps, about 2.4 MB a minute",
  original: "Your files as they are: FLAC stays FLAC",
};

export const EQ_BANDS = [60, 150, 400, 1000, 2400, 15000];

// The usual equalizer presets, plus Metal (dB per band, 60 Hz to 15 kHz).
export const EQ_PRESETS = {
  Flat: [0, 0, 0, 0, 0, 0],
  Acoustic: [4, 3, 1, 1.5, 3, 2.5],
  "Bass Booster": [6, 4, 1.5, 0, 0, 0],
  "Bass Reducer": [-6, -4, -1.5, 0, 0, 0],
  Classical: [4, 3, -1, -1, 2, 4],
  Dance: [4, 6, 2, 0, 2, 1],
  Deep: [4.5, 2, 1, -1, -3, -4.5],
  Electronic: [4, 3, 0, -2, 2, 4.5],
  "Hip-Hop": [5, 4, 1, -1, 1, 2.5],
  Jazz: [3.5, 2, -1, 1.5, 2.5, 3.5],
  Latin: [2.5, 1, -1, -1, 2, 4.5],
  Loudness: [5.5, 2.5, -1, -1, 2, 5.5],
  Lounge: [-2.5, 0, 2, 1, 0, -1],
  // Shelf's own: tight low end, low-mid mud cut, guitar bite and cymbal air.
  Metal: [4.5, 2.5, -3, -0.5, 3.5, 3],
  Piano: [2, 1, 0, 2.5, 3, 2],
  Pop: [-1.5, 1, 4, 4, 1, -1.5],
  "R&B": [5, 4.5, 1, -1.5, 2, 3],
  Rock: [4.5, 3, -1.5, -1, 2, 4],
  "Small Speakers": [5, 4, 2, 0, -1, -3],
  "Spoken Word": [-3, -1, 2, 4, 3, 0],
  "Treble Booster": [0, 0, 0, 1.5, 4, 6],
  "Treble Reducer": [0, 0, 0, -1.5, -4, -6],
  "Vocal Booster": [-2, -1, 2, 4, 3, 0],
};

export const LOUDNESS_TARGETS = { loud: -11, normal: -14, quiet: -19 };

const DEFAULTS = {
  wifiQuality: "auto",
  cellularQuality: "auto",
  autoAdjust: true,
  gapless: true,
  crossfade: 0, // seconds, 0 = off
  crossfadeAlbums: false, // crossfade between songs of the same album too
  autoplay: true,
  mono: false,
  normalize: !IS_IOS, // needs the sound engine, which can stop lock-screen playback on iOS
  loudness: "normal",
  eqEnabled: false,
  eqPreset: "Flat",
  eqGains: [0, 0, 0, 0, 0, 0],
  balance: 0,
  privateSession: false,
  spinDisc: true,
  shelfFormat: "cd", // "cd": jewel cases and a CD; "vinyl": record sleeves and an LP
  deviceName: "", // empty: named after the browser, e.g. "Firefox on Linux"
  downloadQuality: "veryhigh",
};

const values = { ...DEFAULTS, ...store.get("settings", {}) };
const listeners = new Set();

export const settings = {
  get: (key) => values[key],
  all: () => ({ ...values }),
  set(patch) {
    Object.assign(values, patch);
    store.set("settings", values);
    for (const fn of listeners) fn(patch);
  },
  onChange(fn) { listeners.add(fn); return () => listeners.delete(fn); },
  /** True when any setting needs audio to run through the sound engine. */
  needsEngine: () =>
    values.eqEnabled || values.normalize || values.crossfade > 0 || values.mono || Math.abs(values.balance) > 0.001,
};
