// The visualizer on Now Playing: a ring of bars around the disc that move with the music, in
// the album's colour. Off by default (a switch in Now Playing's header): drawing it means routing
// the sound through Web Audio's analyser, which on some phones stops playback in the background.

/** Log-spaced bands from an analyser's dB bins, each 0..1 (`floor` dB silent, `ceil` dB full). */
export function bands(bins, sampleRate, count = 64, lo = 40, hi = 12000, floor = -90, ceil = -25) {
  const out = new Float32Array(count);
  const binHz = sampleRate / 2 / bins.length;
  for (let b = 0; b < count; b++) {
    const f0 = lo * (hi / lo) ** (b / count), f1 = lo * (hi / lo) ** ((b + 1) / count);
    const i0 = Math.max(0, Math.floor(f0 / binHz)), i1 = Math.min(bins.length - 1, Math.max(i0, Math.ceil(f1 / binHz)));
    let peak = -Infinity;
    for (let i = i0; i <= i1; i++) peak = Math.max(peak, bins[i]);
    out[b] = Math.min(1, Math.max(0, (peak - floor) / (ceil - floor)));
  }
  return out;
}

/** Bars rise at once and fall back gently, so the ring moves smoothly. */
export function smooth(prev, next, fall = 0.12) {
  for (let i = 0; i < next.length; i++) prev[i] = next[i] > prev[i] ? next[i] : Math.max(next[i], prev[i] - fall);
  return prev;
}

/** Draw around `around` (the disc), and keep drawing until the returned stop() is called. */
export function startRing(canvas, deck, spectrum, color) {
  const ctx = canvas.getContext("2d");
  let levels = new Float32Array(64), frame = 0;
  const draw = () => {
    frame = requestAnimationFrame(draw);
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (canvas.width !== Math.round(w * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const s = spectrum();
    if (!s) return;
    levels = smooth(levels, bands(s.bins, s.sampleRate));
    const box = canvas.getBoundingClientRect(), d = deck.getBoundingClientRect();
    const cx = d.left - box.left + d.width / 2, cy = d.top - box.top + d.height / 2;
    const r = Math.min(d.width, d.height) / 2 * 1.04, len = r * 0.22;
    ctx.strokeStyle = color(); ctx.lineCap = "round"; ctx.lineWidth = Math.max(2, r * 0.025);
    for (let i = 0; i < levels.length * 2; i++) { // mirrored: lows at the top, highs at the bottom, on both sides
      const v = levels[i < levels.length ? i : levels.length * 2 - 1 - i];
      const a = -Math.PI / 2 + (i / (levels.length * 2)) * Math.PI * 2;
      const l = 2 + v * len;
      ctx.globalAlpha = 0.35 + 0.65 * v;
      ctx.beginPath();
      ctx.moveTo(cx + Math.cos(a) * r, cy + Math.sin(a) * r);
      ctx.lineTo(cx + Math.cos(a) * (r + l), cy + Math.sin(a) * (r + l));
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
  };
  draw();
  return () => { cancelAnimationFrame(frame); ctx.clearRect(0, 0, canvas.width, canvas.height); };
}
