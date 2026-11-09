// Small helpers shared by views and the player.

import { offline } from "./offline.js";

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ESC[c]);

export function fmtTime(sec) {
  if (!Number.isFinite(sec) || sec < 0) sec = 0;
  const s = Math.floor(sec % 60), m = Math.floor(sec / 60) % 60, h = Math.floor(sec / 3600);
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
}

export function fmtLength(sec) {
  const min = Math.round(sec / 60);
  if (min < 60) return `${min} min`;
  const h = Math.floor(min / 60), m = min % 60;
  return m ? `${h} hr ${m} min` : `${h} hr`;
}

export const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

export function coverUrl(albumId, version, size = 320) {
  if (!version) return null;
  return offline.coverUrl(albumId) ?? `api/albums/${albumId}/cover?size=${size}&v=${version}`; // saved for downloads
}

const SRCSETS = { 160: [160, 320], 320: [160, 320, 640], 640: [320, 640, 1200], 1200: [640, 1200] };

/**
 * Jewel-case markup for an album (or a track, which carries albumId + cover).
 * data-album-case lets album covers animate between pages.
 */
export function caseHtml(item, { size = 320, cls = "", lazy = true, sizes } = {}) {
  const id = item.albumId ?? item.id;
  const title = item.album ?? item.title ?? "";
  const bg = `--case-bg:${item.color && /^#[0-9a-f]{6}$/i.test(item.color) ? item.color : fallbackColor(title)}`;
  const attrs = `class="case ${cls}" style="${bg}" data-album-case="${id}"`;
  if (!item.cover) return `<span ${attrs}><span class="no-art">${esc(title)}</span></span>`;
  const set = (SRCSETS[size] || [size]).map((w) => `${coverUrl(id, item.cover, w)} ${w}w`).join(", ");
  sizes ??= cls.includes("case-sm") ? "48px" : "(max-width: 760px) 50vw, 220px";
  // Lazy images fade in as they arrive; eager ones (heroes) appear at once so page
  // transitions can capture them.
  const load = lazy ? `loading="lazy" onload="this.classList.add('ld')"` : `class="ld"`;
  return `<span ${attrs}><img src="${coverUrl(id, item.cover, size)}" srcset="${set}" sizes="${sizes}" alt="" ${load} decoding="async"></span>`;
}

const LOSSLESS = new Set(["flac", "alac", "pcm", "wavpack", "ape"]);

/** A listener-facing quality label for one or more tracks, e.g. "CD quality". */
export function quality(tracks) {
  const list = (Array.isArray(tracks) ? tracks : [tracks]).filter(Boolean);
  if (!list.length) return null;
  const lossless = list.every((t) => LOSSLESS.has((t.codec || "").toLowerCase()));
  const kHz = (r) => `${(r / 1000).toFixed(r % 1000 ? 1 : 0)} kHz`;
  if (lossless) {
    const bits = Math.max(...list.map((t) => t.bits || 16));
    const rate = Math.max(...list.map((t) => t.sampleRate || 44100));
    const hires = bits > 16 || rate > 48000;
    const label = hires ? "Hi-Res lossless" : "CD quality";
    return { label, short: label, detail: `${bits}-bit, ${kHz(rate)}`, hires, lossless };
  }
  const codecs = new Set(list.map((t) => (t.codec || "").toUpperCase()));
  if (codecs.size > 1) return { label: "Mixed formats", short: "Mixed", detail: [...codecs].join(", "), lossless: false };
  const kbps = Math.round(list.reduce((n, t) => n + (t.bitrate || 0), 0) / list.length / 1000);
  const codec = [...codecs][0] || "Lossy";
  if (!kbps) return { label: codec, short: codec, detail: "", lossless: false };
  // Snap to the standard bitrate it was encoded at; otherwise it's variable bitrate.
  const std = [96, 128, 160, 192, 224, 256, 320].find((b) => Math.abs(b - kbps) / b < 0.04);
  return std
    ? { label: codec, short: `${codec} ${std}`, detail: `${std} kbps`, lossless: false }
    : { label: codec, short: codec, detail: `Variable bitrate, about ${kbps} kbps`, lossless: false };
}

export function fmtListening(sec) {
  const min = Math.round(sec / 60);
  if (min < 60) return `${min} ${min === 1 ? "minute" : "minutes"}`;
  const h = Math.floor(min / 60), m = min % 60;
  return `${h} hr${m ? ` ${m} min` : ""}`;
}

/** A stable muted color for albums without cover art. */
export function fallbackColor(text) {
  let h = 0;
  for (const ch of String(text)) h = (h * 31 + ch.codePointAt(0)) >>> 0;
  return `hsl(${h % 360} 28% 42%)`;
}

function hexToHsl(hex) {
  const n = parseInt(hex.slice(1), 16);
  const r = ((n >> 16) & 255) / 255, g = ((n >> 8) & 255) / 255, b = (n & 255) / 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2;
  if (max === min) return [0, 0, l];
  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  let h = max === r ? (g - b) / d + (g < b ? 6 : 0) : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [h * 60, s, l];
}

export const isDark = () =>
  document.documentElement.dataset.theme === "dark" ||
  (document.documentElement.dataset.theme !== "light" && matchMedia("(prefers-color-scheme: dark)").matches);

/**
 * Set --album (raw cover color, used for tints) and --album-strong/--album-on (a version
 * of it with enough contrast for buttons and highlighted text) on an element.
 */
export function applyAlbumColor(el, hex) {
  if (!hex || !/^#[0-9a-f]{6}$/i.test(hex)) {
    el.style.removeProperty("--album");
    el.style.removeProperty("--album-strong");
    el.style.removeProperty("--album-on");
    return;
  }
  const [h, s, l] = hexToHsl(hex);
  const dark = isDark();
  const sat = Math.min(s, 0.75);
  const light = dark ? Math.min(Math.max(l, 0.62), 0.75) : Math.min(Math.max(l, 0.3), 0.42);
  const strong = sat < 0.08 ? (dark ? "#e6e9ef" : "#1c2029") : `hsl(${h.toFixed(0)} ${(sat * 100).toFixed(0)}% ${(light * 100).toFixed(0)}%)`;
  el.style.setProperty("--album", hex);
  el.style.setProperty("--album-strong", strong);
  el.style.setProperty("--album-on", dark ? "#12151c" : "#ffffff");
}

let toastTimer;
export function toast(message, ms = 3200) {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), ms);
}

export const store = {
  get(key, fallback) {
    try {
      const v = localStorage.getItem(`shelf.${key}`);
      return v == null ? fallback : JSON.parse(v);
    } catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(`shelf.${key}`, JSON.stringify(value)); } catch { /* private mode */ }
  },
};

export function shuffled(list) {
  const a = list.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

/** A playlist's cover: four album covers in a grid (like a mix tape's insert), one, or a blank. */
export function playlistCover(p, { size = 160, cls = "" } = {}) {
  const c = p.covers || [];
  const img = (x, s) => `<img src="${coverUrl(x.albumId, x.cover, s)}" alt="" loading="lazy" decoding="async">`;
  if (c.length >= 4) return `<span class="pl-cover grid ${cls}">${c.slice(0, 4).map((x) => img(x, size)).join("")}</span>`;
  if (c.length) return `<span class="pl-cover ${cls}">${img(c[0], size * 2)}</span>`;
  return `<span class="pl-cover empty ${cls}"><svg><use href="#i-note"/></svg></span>`;
}

/** A Camelot key tag ("8A"), colored around the wheel like DJ software; minor keys darker. */
export function keyBadge(t) {
  if (!t.camelot) return "";
  const n = parseInt(t.camelot, 10);
  const minor = t.camelot.endsWith("A");
  return `<span class="key-badge${minor ? " minor" : ""}" style="--hue:${((n - 1) * 30 + 75) % 360}" title="${esc(t.key)}">${esc(t.camelot)}</span>`;
}

/** "Mar 4, 2026" for a timestamp in seconds; "Today" / "Yesterday" / "3 days ago" when recent. */
export function fmtAdded(ts) {
  if (!ts) return "";
  const days = Math.floor((Date.now() / 1000 - ts) / 86400);
  if (days < 1) return "Today";
  if (days < 2) return "Yesterday";
  if (days < 7) return `${days} days ago`;
  return new Date(ts * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}
