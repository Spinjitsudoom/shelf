// Party mode, listening along: what this device should do to play what the host plays, where
// they are in it (the same rule as the Android app's PartySync.kt). Another song (or none here)
// loads the host's at their place; drifting more than 2 seconds apart seeks; pausing and playing
// follow; the host stopping pauses here.

export const TOLERANCE = 2;

/** here, host: { trackId, position (seconds), playing }. Returns { load, seekTo, play } (null: leave it). */
export function follow(here, host) {
  if (host.trackId == null) return { load: false, seekTo: null, play: here.playing ? false : null };
  if (here.trackId !== host.trackId) return { load: true, seekTo: host.position, play: host.playing };
  return {
    load: false,
    seekTo: Math.abs(here.position - host.position) > TOLERANCE ? host.position : null,
    play: here.playing !== host.playing ? host.playing : null,
  };
}
