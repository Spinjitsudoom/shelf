// Mix: how one song hands over to the next, like a DJ would.
//
// Each song carries "mix points" measured on the server (see analysis.py): where its sound
// starts and ends, its intro and outro, its first beat, and a beat near the outro with the
// beat length there. From those, plan() works out a transition.
//
// A transition is a preset, optionally with its parts changed in the transition editor:
//   volume  how the two songs' levels cross: smooth, dj (in first, then out), quick, cut
//   eq      what the basses do: none, swap (swapped halfway, so they never clash), kill
//   filter  none, rise (the old song thins out), wash (the new one opens up), sweep (both)
//   bars    its length when the beats are matched; seconds when they aren't
//   shift   where it starts, moved earlier (negative) or later, in bars (or seconds)
//
// While two songs overlap, the incoming one plays slightly faster or slower (pitch kept)
// so the beats line up; afterwards it eases back to its own tempo.

export const STYLES = ["auto", "blend", "swap", "rise", "sweep", "fade", "cut"];
export const STYLE_LABEL = { auto: "Auto", blend: "Blend", swap: "Bass swap", rise: "Rise", sweep: "Sweep", fade: "Fade", cut: "Cut" };
export const STYLE_HELP = {
  auto: "Shelf picks for each pair of songs",
  blend: "A long, beat-matched blend",
  swap: "Quicker, swapping the basses on the beat",
  rise: "Filters this song away as the next one rises",
  sweep: "Filters sweep across both songs",
  fade: "A plain crossfade, no tempo change",
  cut: "No overlap, straight into the next song",
};

export const PRESETS = {
  blend: { volume: "dj", eq: "swap", filter: "none", bars: 8 },
  swap: { volume: "quick", eq: "swap", filter: "none", bars: 4 },
  rise: { volume: "dj", eq: "none", filter: "rise", bars: 4 },
  sweep: { volume: "smooth", eq: "none", filter: "sweep", bars: 4 },
  fade: { volume: "smooth", eq: "none", filter: "none", seconds: 8, free: true }, // free: no tempo matching
  cut: { volume: "cut", eq: "none", filter: "none", cut: true },
};

export const PARTS = {
  volume: { label: "Volume", options: { smooth: "Smooth crossfade", dj: "In, then out", quick: "Quick in, late out", cut: "Switch in the middle" } },
  eq: { label: "EQ", options: { none: "None", swap: "Center bass swap", kill: "Cut outgoing bass" } },
  filter: { label: "Filter", options: { none: "None", rise: "Thin out outgoing", wash: "Open up incoming", sweep: "Both" } },
};

const MAX_STRETCH = 0.08; // the most a song's tempo is changed to match: 8%
const BASS_CUT = -26; // dB
const HP = [30, 1400]; // Hz: the outgoing song's high-pass sweeps up through this
const LP = [350, 20000]; // Hz: the incoming song's low-pass opens through this

/** A stored transition ("swap", or the editor's object) as { preset, ...changed parts }. */
export function normalize(t) {
  if (!t) return { preset: "auto" };
  if (typeof t === "string") return { preset: STYLES.includes(t) ? t : "auto" };
  return { ...t, preset: STYLES.includes(t.preset) ? t.preset : "auto" };
}

/** True when the editor changed something beyond picking a preset. */
export const isCustom = (t) => Object.keys(normalize(t)).some((k) => k !== "preset");

/** Tempo match between an outgoing and incoming song's mix points, or null if too far apart. */
export function tempoMatch(out, inc) {
  if (!out?.outPeriod || !inc?.inPeriod) return null;
  let best = null;
  // A song detected at half or double tempo can still be matched beat for beat.
  for (const mult of [1, 2, 0.5]) {
    const period = inc.inPeriod / mult; // the incoming beat that lines up with an outgoing beat
    const rate = period / out.outPeriod;
    if (!best || Math.abs(rate - 1) < Math.abs(best.rate - 1)) best = { rate, mult, period };
  }
  return Math.abs(best.rate - 1) <= MAX_STRETCH ? best : null;
}

const camelotOk = (a, b) => {
  if (!a || !b) return true; // unknown keys: don't hold it against them
  const n = (c) => parseInt(c, 10), l = (c) => c.slice(-1);
  if (a === b || n(a) === n(b)) return true; // same, or relative major/minor
  if (l(a) !== l(b)) return false;
  const d = Math.abs(n(a) - n(b));
  return d === 1 || d === 11;
};

/** The preset "auto" turns into for this pair. */
export function autoStyle(cur, nxt) {
  if (!cur?.mix || !nxt?.mix || !tempoMatch(cur.mix, nxt.mix)) return "fade";
  return camelotOk(cur.camelot, nxt.camelot) ? "blend" : "swap";
}

/** Every part of a transition, with the preset filled in under what was changed. */
export function resolve(cur, nxt, setting) {
  const s = normalize(setting);
  const style = s.preset === "auto" ? autoStyle(cur, nxt) : s.preset;
  return { ...PRESETS[style], ...s, style };
}

/**
 * When and how `cur` hands over to `nxt`. `duration` is cur's real length in seconds.
 * Times: `start` in cur's time, `inStart` in nxt's; `length` in real seconds.
 */
export function plan(cur, nxt, setting = "auto", duration = cur?.duration ?? 0) {
  const r = resolve(cur, nxt, setting);
  const m = cur?.mix, n = nxt?.mix;
  const end = Math.min(m?.end ?? duration, duration || Infinity);
  const base = { style: r.style, setting: normalize(setting), volume: r.volume, eq: r.eq, filter: r.filter, rate: 1, beatmatch: false };

  if (r.cut) return { ...base, start: end + (r.shift ?? 0), length: 0, inStart: n?.start ?? 0 };

  const match = !r.free && m && n ? tempoMatch(m, n) : null;
  if (match && m.outBeat != null && n.firstBeat != null) {
    const P = m.outPeriod;
    // End the transition just after the outro starts winding down, and start it on a bar.
    const E = Math.min(end, m.outro + 4 * P);
    const earliest = Math.max(m.intro ?? 0, duration * 0.3);
    let beats = Math.round((r.bars ?? 8) * 4);
    while (beats > 4 && beats * P > E - earliest) beats /= 2;
    if (beats * P <= end - earliest) {
      const k = Math.floor((E - beats * P - m.outBeat) / P / 4) * 4 + Math.round((r.shift ?? 0) * 4);
      let start = m.outBeat + k * P;
      while (start + beats * P > end + 0.01) start -= 4 * P; // the song has to still be playing
      while (start < earliest - P) start += 4 * P;
      if (start > 0) {
        return {
          ...base, start, length: beats * P, beats, inStart: n.firstBeat, rate: match.rate, beatmatch: true,
          outRef: m.outBeat, outPeriod: P, inRef: n.firstBeat, inPeriod: match.period,
        };
      }
    }
  }

  // Not beat-matched: a crossfade timed to the outro (here `shift` is in seconds).
  const E = m ? Math.min(end, m.outro + 3) : end;
  const length = Math.min(r.seconds ?? 8, Math.max(2, (duration || 30) / 4));
  const start = Math.max(0, Math.min(end - length, E - length + (r.shift ?? 0)));
  return { ...base, start, length, inStart: n?.start ?? 0 };
}

/**
 * The sound side of a transition, as automation for the engine: for each player, its gain
 * (equal-power curves), bass shelf and filters over the transition's `length` seconds.
 */
export function automation(p) {
  const T = p.length;
  const lanes = { in: { gain: [], bass: [], highpass: [], lowpass: [] }, out: { gain: [], bass: [], highpass: [], lowpass: [] } };
  const vol = {
    smooth: [[0, T, 0, 1], [0, T, 1, 0]],
    dj: [[0, T * 0.5, 0, 1], [T * 0.5, T, 1, 0]],
    quick: [[0, T * 0.25, 0, 1], [T * 0.625, T, 1, 0]],
    cut: [[T * 0.5 - 0.02, T * 0.5 + 0.02, 0, 1], [T * 0.5 - 0.02, T * 0.5 + 0.02, 1, 0]],
  }[p.volume] ?? [[0, T, 0, 1], [0, T, 1, 0]];
  lanes.in.gain.push(vol[0]);
  lanes.out.gain.push(vol[1]);
  if (p.eq === "swap") {
    lanes.in.bass.push([0, BASS_CUT], [T * 0.5, 0]);
    lanes.out.bass.push([T * 0.5, BASS_CUT]);
  } else if (p.eq === "kill") {
    lanes.out.bass.push([0, BASS_CUT]);
  }
  if (p.filter === "rise" || p.filter === "sweep") lanes.out.highpass.push([0, T, ...HP]);
  if (p.filter === "wash" || p.filter === "sweep") lanes.in.lowpass.push([0, T, ...LP]);
  return lanes;
}

/**
 * For drawing: each lane's volume, bass and filter at x (0..1 through the transition),
 * from 0 to 1. Outside the transition the outgoing song is at full and the incoming silent.
 */
export function levels(auto, T, side, x) {
  const t = x * T;
  const lane = auto[side];
  let gain = side === "out" ? 1 : 0;
  for (const [t0, t1, a, b] of lane.gain) {
    if (t <= t0) gain = a;
    else if (t >= t1) gain = b;
    else {
      const u = (t - t0) / (t1 - t0);
      gain = a < b ? a + (b - a) * Math.sin(u * Math.PI / 2) : b + (a - b) * Math.cos(u * Math.PI / 2);
    }
  }
  let bass = 1;
  for (const [at, db] of lane.bass) if (t >= at) bass = db < -1 ? 0 : 1;
  // How open the filter is (the sweeps are exponential, so this is linear in time).
  let filter = 1;
  const u = (t0, t1) => Math.min(1, Math.max(0, (t - t0) / (t1 - t0)));
  for (const [t0, t1] of lane.highpass) filter = 1 - u(t0, t1);
  for (const [t0, t1] of lane.lowpass) filter = u(t0, t1);
  return { gain, bass, filter, hasBass: lane.bass.length > 0, hasFilter: lane.highpass.length + lane.lowpass.length > 0 };
}

/** A short description, for the transition pill's tooltip. */
export function describe(cur, nxt, setting) {
  const p = plan(cur, nxt, setting);
  const what = STYLE_LABEL[p.style] ?? "Fade";
  if (p.length === 0) return `${what}: straight into the next song`;
  if (!p.beatmatch) return `${what}: ${Math.round(p.length)} second crossfade`;
  const pct = Math.round((p.rate - 1) * 1000) / 10;
  return `${what}: ${barsLabel(p.beats / 4)}${pct ? `, next song ${pct > 0 ? "sped up" : "slowed"} ${Math.abs(pct)}% to match` : ", same tempo"}`;
}

export const barsLabel = (bars) => (bars === 1 ? "1 bar" : bars < 1 ? `${bars * 4} beats` : `${bars} bars`);
