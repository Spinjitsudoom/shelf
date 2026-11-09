// The mixer screen: six faders, a draggable EQ curve, and the live spectrum behind it.

import { eqResponse } from "./audio.js";
import { EQ_BANDS, EQ_PRESETS, settings } from "./settings.js";
import { balanceLabel, fmtDb } from "./views.js";

const F_MIN = 20, F_MAX = 20000, DB = 12;

// The frequency axis is logarithmic between anchors, and the anchors are the faders: each
// band's handle on the curve sits right above its own fader, wherever the layout puts it.
let anchors = [[0, Math.log(F_MIN)], [1, Math.log(F_MAX)]]; // [x, log f], x rising
function between(v, from, to) {
  for (let i = 1; i < anchors.length; i++) {
    const a = anchors[i - 1], b = anchors[i];
    if (v <= b[from] || i === anchors.length - 1) return a[to] + ((v - a[from]) / ((b[from] - a[from]) || 1)) * (b[to] - a[to]);
  }
  return 0;
}
const xToFreq = (x) => Math.exp(between(x, 0, 1));
const freqToX = (f) => between(Math.log(f), 1, 0);

function colors() {
  const cs = getComputedStyle(document.documentElement);
  const v = (n) => cs.getPropertyValue(n).trim();
  return { accent: v("--cobalt"), ink: v("--ink"), ink2: v("--ink-2"), rule: v("--rule"), sleeve: v("--sleeve") };
}

function setFaderFill(input) {
  const pct = ((Number(input.value) + DB) / (2 * DB)) * 100;
  input.style.setProperty("--lo", `${Math.min(50, pct)}%`);
  input.style.setProperty("--hi", `${Math.max(50, pct)}%`);
}

/** Wire up the mixer view. Returns a cleanup function for when the page is left. */
export function mountMixer(root, player) {
  const canvas = root.querySelector("#eq-canvas");
  const ctx2d = canvas.getContext("2d");
  const panel = root.querySelector("#eq-panel");
  const faders = [...root.querySelectorAll(".vfader")];
  const presetSel = root.querySelector("#eq-preset");
  let raf = 0, w = 0, h = 0, curve = null, curveKey = "", dragBand = -1;

  const gains = () => settings.get("eqGains");

  function setGains(next, preset = "Custom") {
    settings.set({ eqGains: next, eqPreset: preset, eqEnabled: true });
    player.enableEngineIfNeeded();
    sync();
  }

  function sync() {
    const g = gains();
    faders.forEach((f, i) => {
      if (Number(f.value) !== g[i]) f.value = g[i];
      setFaderFill(f);
      f.setAttribute("aria-valuetext", `${fmtDb(g[i])} decibels`);
      root.querySelector(`#eq-out-${i}`).textContent = fmtDb(g[i]);
    });
    const preset = settings.get("eqPreset");
    if (preset === "Custom" && !presetSel.querySelector('option[value="Custom"]')) {
      presetSel.insertAdjacentHTML("afterbegin", '<option value="Custom">Custom</option>');
    }
    presetSel.value = preset;
    panel.classList.toggle("off", !settings.get("eqEnabled"));
    root.querySelector('.switch[data-setting="eqEnabled"]')?.setAttribute("aria-checked", String(settings.get("eqEnabled")));
    const bal = root.querySelector('[data-setting="balance"]');
    if (bal) {
      bal.style.setProperty("--pct", `${((settings.get("balance") + 1) / 2) * 100}%`);
      root.querySelector('[data-out="balance"]').textContent = balanceLabel(settings.get("balance"));
    }
    draw();
  }

  function resize() {
    const r = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    w = r.width; h = r.height;
    const centres = faders.map((f) => { const b = f.getBoundingClientRect(); return b.left + b.width / 2 - r.left; });
    anchors = centres.every((x, i) => x > (centres[i - 1] ?? 0) && x < w)
      ? [[0, Math.log(F_MIN)], ...EQ_BANDS.map((f, i) => [centres[i], Math.log(f)]), [w, Math.log(F_MAX)]]
      : [[0, Math.log(F_MIN)], [w, Math.log(F_MAX)]];
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    ctx2d.setTransform(dpr, 0, 0, dpr, 0, 0);
    curveKey = "";
    draw();
  }

  const yOf = (db) => h / 2 - (db / DB) * (h / 2 - 14);

  function draw() {
    if (!w) return;
    const c = colors();
    const on = settings.get("eqEnabled");
    const g = on ? gains() : [0, 0, 0, 0, 0, 0];
    ctx2d.clearRect(0, 0, w, h);

    // grid: 0 dB line, ±6/12 dB, and the band frequencies
    ctx2d.lineWidth = 1;
    for (const db of [-12, -6, 0, 6, 12]) {
      ctx2d.strokeStyle = c.rule;
      ctx2d.globalAlpha = db === 0 ? 1 : 0.5;
      ctx2d.beginPath(); ctx2d.moveTo(0, Math.round(yOf(db)) + 0.5); ctx2d.lineTo(w, Math.round(yOf(db)) + 0.5); ctx2d.stroke();
    }
    ctx2d.globalAlpha = 1;

    // live spectrum of what's playing, faint, behind the curve
    const spec = player.engine.spectrum();
    if (spec && player.playing) {
      const { bins, sampleRate } = spec;
      const nyq = sampleRate / 2;
      ctx2d.beginPath();
      ctx2d.moveTo(0, h);
      for (let x = 0; x <= w; x += 2) {
        const bin = Math.min(bins.length - 1, Math.round((xToFreq(x) / nyq) * bins.length));
        const v = Math.max(0, Math.min(1, (bins[bin] + 95) / 75));
        ctx2d.lineTo(x, h - v * h * 0.85);
      }
      ctx2d.lineTo(w, h);
      ctx2d.closePath();
      ctx2d.fillStyle = c.ink;
      ctx2d.globalAlpha = 0.07;
      ctx2d.fill();
      ctx2d.globalAlpha = 1;
    }

    // the EQ curve
    const key = `${w}|${g.join(",")}`;
    if (key !== curveKey) {
      const n = Math.max(64, Math.round(w / 2));
      const freqs = new Float32Array(n);
      for (let i = 0; i < n; i++) freqs[i] = xToFreq((i / (n - 1)) * w);
      curve = eqResponse(g, freqs);
      curveKey = key;
    }
    ctx2d.beginPath();
    curve.forEach((db, i) => {
      const x = (i / (curve.length - 1)) * w, y = yOf(Math.max(-DB, Math.min(DB, db)));
      if (i) ctx2d.lineTo(x, y); else ctx2d.moveTo(x, y);
    });
    ctx2d.strokeStyle = on ? c.accent : c.ink2;
    ctx2d.lineWidth = 2.5;
    ctx2d.lineJoin = "round";
    ctx2d.stroke();
    ctx2d.lineTo(w, yOf(0)); ctx2d.lineTo(0, yOf(0)); ctx2d.closePath();
    ctx2d.fillStyle = on ? c.accent : c.ink2;
    ctx2d.globalAlpha = 0.12;
    ctx2d.fill();
    ctx2d.globalAlpha = 1;

    // dB scale, drawn over the curve with a halo so it stays readable
    ctx2d.font = "600 11px Archivo, system-ui, sans-serif";
    ctx2d.lineWidth = 3;
    ctx2d.strokeStyle = c.sleeve;
    ctx2d.fillStyle = c.ink2;
    for (const [text, y] of [["+12", yOf(12) - 4], ["0 dB", yOf(0) - 4], ["−12", yOf(-12) + 13]]) {
      ctx2d.strokeText(text, 6, y);
      ctx2d.fillText(text, 6, y);
    }

    // band handles
    EQ_BANDS.forEach((f, i) => {
      const x = freqToX(f), y = yOf(g[i]);
      ctx2d.beginPath();
      ctx2d.arc(x, y, dragBand === i ? 8 : 6, 0, Math.PI * 2);
      ctx2d.fillStyle = on ? c.accent : c.ink2;
      ctx2d.fill();
      ctx2d.lineWidth = 2.5;
      ctx2d.strokeStyle = c.sleeve;
      ctx2d.stroke();
    });
  }

  function loop() {
    draw();
    raf = player.playing && player.engine.active ? requestAnimationFrame(loop) : 0;
  }
  const kick = () => { if (!raf) raf = requestAnimationFrame(loop); };

  // faders
  faders.forEach((f) => {
    setFaderFill(f);
    f.addEventListener("input", () => {
      const next = gains().slice();
      next[Number(f.dataset.band)] = Number(f.value);
      setGains(next);
    });
  });
  presetSel.addEventListener("change", () => {
    const name = presetSel.value;
    if (EQ_PRESETS[name]) setGains(EQ_PRESETS[name].slice(), name);
  });

  // drag the curve's handles
  const bandAt = (x) => {
    let best = -1, dist = Infinity;
    EQ_BANDS.forEach((f, i) => { const d = Math.abs(freqToX(f) - x); if (d < dist) { dist = d; best = i; } });
    return dist < 40 ? best : -1;
  };
  const dbAt = (y) => Math.round(Math.max(-DB, Math.min(DB, ((h / 2 - y) / (h / 2 - 14)) * DB)) * 2) / 2;
  canvas.addEventListener("pointerdown", (e) => {
    const r = canvas.getBoundingClientRect();
    dragBand = bandAt(e.clientX - r.left);
    if (dragBand < 0) return;
    canvas.setPointerCapture(e.pointerId);
    const next = gains().slice();
    next[dragBand] = dbAt(e.clientY - r.top);
    setGains(next);
  });
  canvas.addEventListener("pointermove", (e) => {
    if (dragBand < 0) return;
    const r = canvas.getBoundingClientRect();
    const next = gains().slice();
    next[dragBand] = dbAt(e.clientY - r.top);
    if (next[dragBand] !== gains()[dragBand]) setGains(next);
  });
  const endDrag = () => { if (dragBand >= 0) { dragBand = -1; draw(); } };
  canvas.addEventListener("pointerup", endDrag);
  canvas.addEventListener("pointercancel", endDrag);

  const ro = new ResizeObserver(resize);
  ro.observe(canvas);
  const offSettings = settings.onChange(() => sync());
  const onState = () => kick();
  player.addEventListener("state", onState);
  const mq = matchMedia("(prefers-color-scheme: dark)");
  mq.addEventListener("change", draw);
  resize();
  sync();
  kick();

  return () => {
    cancelAnimationFrame(raf);
    ro.disconnect();
    offSettings();
    player.removeEventListener("state", onState);
    mq.removeEventListener("change", draw);
  };
}
