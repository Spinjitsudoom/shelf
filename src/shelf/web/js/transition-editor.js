// "Edit transition": how one song in a Mix playlist hands over to the next.
//
// Both songs' waveforms are drawn on one timeline (the outgoing song above, the incoming
// one below, its tempo already matched), with the bass in amber. Lines over them show what
// the transition does: volume in blue, bass in yellow, filter in pink. Dragging the
// waveforms moves where the transition starts (snapped to bars), the chip under them sets
// its length, presets set everything at once, and Volume, EQ and Filter change one part.
// The play button previews it for real, on this device's player.

import { api } from "./api.js";
import { openMenu } from "./menu.js";
import {
  PARTS, STYLES, STYLE_HELP, STYLE_LABEL, automation, barsLabel, describe, levels, normalize, plan,
} from "./transitions.js";
import { caseHtml, esc, keyBadge } from "./util.js";

const COLORS = { volume: "#4cc2ff", bass: "#ffd23f", filter: "#ff6fb5", wave: "rgba(246, 196, 150, .9)", low: "rgba(70, 104, 255, .9)", head: "#3ddc84" };
// Loud masters sit near the top of the meter all the time; this curve brings out the beats.
const shape = (v) => Math.max(0, (v - 0.3) / 0.7) ** 1.4;
const SAME = (a, b) => JSON.stringify(normalize(a)) === JSON.stringify(normalize(b));

/**
 * Show the editor in `host`. `tracks[index]` hands over to `tracks[index + 1]`.
 * `onSave(setting)` stores it; `onClose()` is called when it's closed either way.
 */
export function mountTransitionEditor(host, { player, tracks, index, context, onSave, onClose }) {
  const cur = tracks[index], nxt = tracks[index + 1];
  const original = normalize(cur.transition);
  let draft = { ...original };
  let p = plan(cur, nxt, draft, cur.duration);
  let waves = { out: null, in: null };
  let previewing = false;
  let drag = null; // { x0, shift0, units }
  let dead = false;

  const trackLine = (t, side) => `
    <div class="tre-track ${side}">
      ${caseHtml(t, { size: 160, cls: "case-sm", sizes: "32px" })}
      <span class="tre-name"><b>${esc(t.title)}</b><span>${esc(t.artist)}</span></span>
      <span class="tre-facts">${t.bpm ? `${t.bpm} BPM` : ""}${keyBadge(t)}</span>
    </div>`;

  host.innerHTML = `
    <div class="tre">
      <div class="tre-head">
        <h2>Edit transition</h2>
        <button class="btn btn-small btn-primary" type="button" data-tre="save" disabled>Save</button>
        <button class="icon-btn" type="button" data-tre="close" aria-label="Close" title="Close"><svg><use href="#i-close"/></svg></button>
      </div>
      ${trackLine(cur, "out")}
      <div class="tre-stage">
        <canvas class="tre-canvas" aria-label="Both songs' waveforms through the transition. Drag to move where it starts."></canvas>
        <button class="tre-play" type="button" data-tre="play" aria-label="Preview the transition" title="Preview"><svg><use href="#i-play"/></svg></button>
        <button class="tre-len" type="button" data-tre="length" aria-haspopup="menu"></button>
      </div>
      ${trackLine(nxt, "in")}
      <p class="tre-label">Presets</p>
      <div class="tre-presets" role="group" aria-label="Presets">${STYLES.map((s) =>
        `<button class="chip" type="button" data-preset="${s}" title="${esc(STYLE_HELP[s])}">${s === "auto" ? `<svg><use href="#i-sparkle"/></svg>` : ""}${STYLE_LABEL[s]}</button>`).join("")}</div>
      <div class="tre-parts">${Object.entries(PARTS).map(([key, part]) => `
        <label class="tre-part"><span class="tre-mark ${key}"></span><span class="tre-part-name">${part.label}</span>
          <select data-part="${key}">${Object.entries(part.options).map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join("")}</select>
        </label>`).join("")}</div>
      <p class="tre-note" id="tre-note"></p>
    </div>`;
  const $ = (sel) => host.querySelector(sel);
  const canvas = $(".tre-canvas");

  // ---- drawing ----

  /** The visible stretch of the outgoing song's timeline: the transition, with some either side. */
  const view = () => {
    const pad = Math.max(4, (p.length || 4) * 0.55);
    return { from: p.start - pad, to: p.start + (p.length || 0) + pad };
  };
  /** Incoming song time at a point on the outgoing timeline. */
  const inTime = (t) => p.inStart + (t - p.start) * (p.rate || 1);

  function sample(w, t) {
    if (!w || t < w.start || t >= w.end) return null;
    const i = Math.floor((t - w.start) / w.step);
    return i >= 0 && i < w.full.length ? [w.full[i], w.bass[i]] : null;
  }

  function draw() {
    if (dead) return;
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.clientWidth, H = canvas.clientHeight;
    if (!W || !H) return;
    if (canvas.width !== Math.round(W * dpr)) { canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr); }
    const g = canvas.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, W, H);
    const v = view();
    const X = (t) => ((t - v.from) / (v.to - v.from)) * W;
    const lane = { out: [10, H / 2 - 6], in: [H / 2 + 6, H - 10] };
    const x0 = X(p.start), x1 = X(p.start + p.length);

    // the transition itself, lit; bar lines when the beats are matched
    g.fillStyle = "rgba(255,255,255,.05)";
    g.fillRect(x0, 0, Math.max(2, x1 - x0), H);
    if (p.beatmatch) {
      g.strokeStyle = "rgba(255,255,255,.07)";
      g.lineWidth = 1;
      const bar = p.outPeriod * 4;
      for (let t = p.outRef + Math.ceil((v.from - p.outRef) / bar) * bar; t < v.to; t += bar) {
        g.beginPath(); g.moveTo(Math.round(X(t)) + 0.5, 0); g.lineTo(Math.round(X(t)) + 0.5, H); g.stroke();
      }
    }

    // waveforms: mirrored around each lane's middle, bass drawn over in amber
    for (const side of ["out", "in"]) {
      const [top, bottom] = lane[side];
      const mid = (top + bottom) / 2, half = (bottom - top) / 2;
      for (let x = 0; x < W; x += 2) {
        const t = v.from + (x / W) * (v.to - v.from);
        const s = side === "out" ? sample(waves.out, t) : sample(waves.in, inTime(t));
        if (!s) continue;
        const playing = side === "out" ? t <= p.start + p.length : t >= p.start;
        g.globalAlpha = playing ? 1 : 0.28;
        // Height from the overall level; the blue core is the bass's share of it.
        const share = Math.min(1, 10 ** (((s[1] - s[0]) * 48) / 10));
        const hi = shape(s[0]) * half, lo = hi * Math.sqrt(share) * 0.78;
        g.fillStyle = COLORS.wave;
        g.fillRect(x, mid - hi, 1.6, hi * 2);
        g.fillStyle = COLORS.low;
        g.fillRect(x, mid - lo, 1.6, lo * 2);
      }
      g.globalAlpha = 1;
    }

    // what the transition does, lane by lane
    const auto = automation(p);
    for (const side of ["out", "in"]) {
      const [top, bottom] = lane[side];
      const Y = (val) => bottom - 4 - val * (bottom - top - 8);
      for (const [key, color] of [["filter", COLORS.filter], ["bass", COLORS.bass], ["gain", COLORS.volume]]) {
        const at = (t) => {
          const x = p.length ? (t - p.start) / p.length : t < p.start ? 0 : 1;
          return levels(auto, p.length || 0.001, side, Math.min(1, Math.max(0, x)));
        };
        const probe = at(p.start + p.length / 2);
        if (key === "bass" && !probe.hasBass) continue;
        if (key === "filter" && !probe.hasFilter) continue;
        g.beginPath();
        for (let x = 0; x <= W; x += 2) {
          const t = v.from + (x / W) * (v.to - v.from);
          const y = Y(at(t)[key]);
          if (x === 0) g.moveTo(x, y); else g.lineTo(x, y);
        }
        // a dark edge first, so the line reads over the waveform
        g.strokeStyle = "rgba(10, 12, 18, .7)";
        g.lineWidth = key === "gain" ? 5.5 : 5;
        g.stroke();
        g.strokeStyle = color;
        g.lineWidth = key === "gain" ? 2.5 : 2;
        g.stroke();
      }
    }

    // preview playhead
    const head = playhead();
    if (head != null && head >= v.from && head <= v.to) {
      g.strokeStyle = COLORS.head;
      g.lineWidth = 2;
      g.beginPath(); g.moveTo(X(head), 0); g.lineTo(X(head), H); g.stroke();
    }
  }

  /** Where the preview has got to, on the outgoing song's timeline. */
  function playhead() {
    if (!previewing) return null;
    const c = player.current;
    if (c?.id === cur.id && player.index === index) return player.position;
    if (c?.id === nxt.id && player.index === index + 1) return p.start + (player.position - p.inStart) / (p.rate || 1);
    return null;
  }

  // ---- state ----

  function update() {
    p = plan(cur, nxt, draft, cur.duration);
    const resolved = { volume: p.volume, eq: p.eq, filter: p.filter };
    host.querySelectorAll("[data-preset]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.preset === draft.preset)));
    host.querySelectorAll("[data-part]").forEach((s) => { s.value = resolved[s.dataset.part]; s.disabled = p.length === 0; });
    const len = $(".tre-len");
    len.textContent = p.length === 0 ? "No overlap" : p.beatmatch ? barsLabel(p.beats / 4) : `${Math.round(p.length)} seconds`;
    len.disabled = p.length === 0;
    $("[data-tre=save]").disabled = SAME(draft, original);
    const note = describe(cur, nxt, draft);
    $("#tre-note").textContent = `${note}. ${p.length === 0 ? "" : "Drag the waveforms to move where it starts."}`;
    draw();
  }

  // ---- interaction ----

  host.addEventListener("click", (e) => {
    const preset = e.target.closest("[data-preset]");
    if (preset) { draft = { preset: preset.dataset.preset }; update(); return; }
    const b = e.target.closest("[data-tre]");
    if (!b) return;
    const what = b.dataset.tre;
    if (what === "close") close();
    else if (what === "save") { stopPreview(); onSave(normalize(draft)); close(true); }
    else if (what === "play") previewing ? stopPreview() : startPreview();
    else if (what === "length") lengthMenu(b);
  });
  host.addEventListener("change", (e) => {
    const s = e.target.closest("[data-part]");
    if (!s) return;
    draft = { ...draft, [s.dataset.part]: s.value };
    update();
  });

  function lengthMenu(at) {
    const opts = p.beatmatch ? [1, 2, 4, 8, 16] : [2, 4, 6, 8, 12, 16];
    const now = p.beatmatch ? p.beats / 4 : Math.round(p.length);
    openMenu({
      at,
      heading: "Length",
      items: opts.map((o) => ({
        label: p.beatmatch ? barsLabel(o) : `${o} seconds`, icon: o === now ? "i-check" : "i-clock", current: o === now,
        run: () => {
          draft = p.beatmatch ? { ...draft, bars: o, seconds: undefined } : { ...draft, seconds: o, bars: undefined };
          draft = JSON.parse(JSON.stringify(draft)); // drop the undefined key
          update();
        },
      })),
    });
  }

  // Drag to move the transition: the waveforms slide under it, a bar (or second) at a time.
  canvas.addEventListener("pointerdown", (e) => {
    if (p.length === 0) return;
    canvas.setPointerCapture(e.pointerId);
    drag = { x0: e.clientX, shift0: draft.shift ?? 0, units: 0 };
    canvas.classList.add("dragging");
  });
  canvas.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const v = view();
    const secPerPx = (v.to - v.from) / canvas.clientWidth;
    const unit = p.beatmatch ? p.outPeriod * 4 : 1;
    const units = -Math.round(((e.clientX - drag.x0) * secPerPx) / unit);
    if (units === drag.units) return;
    const before = p.start;
    const trial = { ...draft, shift: drag.shift0 + units };
    if (plan(cur, nxt, trial, cur.duration).start === before && units !== 0) return; // at the limit
    drag.units = units;
    draft = trial.shift === 0 ? (({ shift, ...rest }) => rest)(trial) : trial;
    update();
  });
  const endDrag = () => { if (drag) { drag = null; canvas.classList.remove("dragging"); } };
  canvas.addEventListener("pointerup", endDrag);
  canvas.addEventListener("pointercancel", endDrag);

  // ---- preview ----

  function startPreview() {
    const queue = tracks.map((t, i) => (i === index ? { ...t, transition: normalize(draft) } : t));
    const lead = Math.min(6, Math.max(3, (p.length || 4) * 0.5));
    player.playList(queue, index, { context: { ...context, mix: true }, startAt: Math.max(0, p.start - lead) });
    previewing = true;
    setPlayIcon();
  }
  function stopPreview() {
    if (!previewing) return;
    previewing = false;
    player.pause();
    setPlayIcon();
    draw();
  }
  function setPlayIcon() {
    $(".tre-play use").setAttribute("href", previewing ? "#i-pause" : "#i-play");
    $(".tre-play").setAttribute("aria-label", previewing ? "Stop the preview" : "Preview the transition");
  }
  const onTime = () => {
    if (!previewing) return;
    const h = playhead();
    // Stop a few seconds after the transition, or if something else started playing.
    if (h == null || h > p.start + p.length + 4) { stopPreview(); return; }
    draw();
  };
  player.addEventListener("time", onTime);

  const resize = new ResizeObserver(() => draw());
  resize.observe(canvas);

  function close(saved = false) {
    if (dead) return;
    dead = true;
    if (!saved) stopPreview();
    player.removeEventListener("time", onTime);
    resize.disconnect();
    onClose();
  }

  // The two waveforms around the transition, wide enough to drag it a fair way.
  const outFrom = Math.max(0, Math.min(p.start, cur.mix?.outro ?? p.start) - 75);
  Promise.all([
    api.peaks(cur.id, outFrom, cur.duration + 1).catch(() => null),
    api.peaks(nxt.id, 0, 90).catch(() => null),
  ]).then(([o, i]) => { waves = { out: o, in: i }; draw(); });

  update();
  return { close: () => close(), get dirty() { return !SAME(draft, original); } };
}
