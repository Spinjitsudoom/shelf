// Long tracks (live sets, DJ mixes, audiobooks) pick up where you stopped, on any of your devices.
// The place is kept on the server every 15 seconds while one plays, and when it's paused or left.

import { api } from "./api.js";

export const LONG = 15 * 60; // seconds

export const isLong = (t) => (t?.duration ?? 0) >= LONG;

/** Where you stopped in this track (0: from the start). */
export async function placeIn(t) {
  try { return (await api.resumeAt(t.id)).position || 0; } catch { return 0; }
}

let last = { id: null, at: 0 };

/** Keeps the place in a long track: now (`force`), or at most every 15 seconds. */
export function keepPlace(t, sec, force = false) {
  if (!isLong(t) || !Number.isFinite(sec)) return;
  const now = Date.now();
  if (!force && last.id === t.id && now - last.at < 15000) return;
  last = { id: t.id, at: now };
  api.keepPlace(t.id, sec);
}
