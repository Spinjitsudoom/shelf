// Thin fetch wrapper with a small cache so moving around the app is instant.
// Cached pages show immediately and refresh quietly in the background.
// A 401 anywhere sends the app back to the sign-in screen.
// With no connection, requests fail with status 0 and the app switches to offline mode:
// downloaded albums, playlists and Favourites still open, from what was saved with them.

import { offline } from "./offline.js";

let onUnauthorized = () => {};
export const setUnauthorizedHandler = (fn) => { onUnauthorized = fn; };

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

export let isOffline = false;

function setOffline(on) {
  if (on === isOffline) return;
  isOffline = on;
  document.body.classList.toggle("offline", on);
  window.dispatchEvent(new CustomEvent("connection-changed", { detail: { offline: on } }));
}

async function request(method, path, body) {
  let res;
  try {
    res = await fetch(`api/${path}`, {
      method,
      credentials: "same-origin",
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    setOffline(true);
    throw new ApiError(0, "You’re offline");
  }
  // A proxy or the phone itself may answer for an unreachable server.
  if (res.status === 502 || res.status === 503 || res.status === 504) {
    setOffline(true);
    throw new ApiError(0, "Can’t reach the server");
  }
  setOffline(false);
  if (res.status === 401 && path !== "login" && path !== "logout") {
    onUnauthorized();
    throw new ApiError(401, "Not signed in");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch { /* not JSON */ }
    throw new ApiError(res.status, detail);
  }
  return res.json();
}

/** Offline: what was saved with a downloaded album, playlist or Favourites, if it was. */
function savedOr(err, key) {
  if (err.status === 0) {
    const data = offline.data(key);
    if (data) return structuredCloneSafe(data);
  }
  throw err;
}
const structuredCloneSafe = (x) => JSON.parse(JSON.stringify(x));

const cache = new Map(); // path -> { at, promise }

/** Stale-while-revalidate GET: returns cached data at once, refreshes it if older than maxAge. */
function cached(path, maxAge = 30_000) {
  const hit = cache.get(path);
  const now = Date.now();
  if (hit) {
    if (now - hit.at > maxAge) {
      const fresh = request("GET", path);
      fresh.then(() => cache.set(path, { at: Date.now(), promise: fresh }), () => {});
    }
    return hit.promise;
  }
  const promise = request("GET", path);
  cache.set(path, { at: now, promise });
  promise.catch(() => cache.delete(path));
  return promise;
}

export const isCached = (path) => cache.has(path);
export function invalidate(prefix = "") {
  for (const key of cache.keys()) if (key.startsWith(prefix)) cache.delete(key);
}

/** Playlist edits refresh every list of playlists on screen. */
async function changed(promise) {
  const r = await promise;
  invalidate("playlists");
  window.dispatchEvent(new CustomEvent("playlists-changed"));
  return r;
}

export const api = {
  session: () => request("GET", "session"),
  login: (username, password) => request("POST", "login", { username, password }),
  setup: (username, password) => request("POST", "setup", { username, password }),
  changePassword: (current, next) => request("PUT", "me/password", { current, new: next }),
  users: () => request("GET", "users"),
  createUser: (body) => request("POST", "users", body),
  editUser: (id, body) => request("PATCH", `users/${id}`, body),
  signOutUser: (id) => request("POST", `users/${id}/signout`),
  deleteUser: (id) => request("DELETE", `users/${id}`),
  adminOverview: () => request("GET", "admin/overview"),
  checkUpdate: () => request("POST", "admin/update/check"),
  updateServer: () => request("POST", "admin/update"),
  setWatchFolder: (path) => request("PATCH", "admin/watch", { path }),
  backUpNow: () => request("POST", "admin/backups"),
  libraryHealth: () => request("GET", "admin/health"),
  findMissingCovers: () => request("POST", "admin/covers/find-missing"),
  coverCandidates: (albumId) => request("GET", `admin/covers/${albumId}/candidates`),
  useCover: (albumId, mbid) => changed(request("POST", `admin/covers/${albumId}`, { mbid })),
  dropFoundCover: (albumId) => changed(request("DELETE", `admin/covers/${albumId}`)),
  setBackupFolder: (folder) => request("PATCH", "admin/backups", { folder }),
  restoreBackup: (name) => request("POST", `admin/backups/${encodeURIComponent(name)}/restore`),
  setLastfmKeys: (key, secret) => request("PATCH", "admin/lastfm", { key, secret }),
  lastfmStart: () => request("POST", "me/lastfm/start"),
  lastfmFinish: () => request("POST", "me/lastfm/finish"),
  lastfmDisconnect: () => request("DELETE", "me/lastfm"),
  subsonic: () => request("GET", "me/subsonic"),
  subsonicOn: () => request("POST", "me/subsonic"),
  subsonicOff: () => request("DELETE", "me/subsonic"),
  autoUpdate: (enabled) => request("PATCH", "admin/update/auto", { enabled }),
  clearSignins: (address) => request("DELETE", `admin/signins${address ? `?address=${encodeURIComponent(address)}` : ""}`),
  logout: () => { invalidate(); return request("POST", "logout"); },
  library: () => request("GET", "library"),
  rescan: () => { invalidate(); return request("POST", "scan"); },
  home: () => request("GET", "home"),
  albums: (sort = "artist") => cached(`albums?sort=${encodeURIComponent(sort)}`),
  artistAlbums: (name) => cached(`albums?artist=${encodeURIComponent(name)}`),
  // Each track carries its album's loudness, for album-mode volume normalization.
  album: (id) => cached(`albums/${id}`, 120_000).then((a) => {
    for (const t of a.tracks) { t.albumLufs = a.albumLufs; t.albumPeak = a.albumPeak; }
    return a;
  }, (e) => savedOr(e, `album:${id}`)),
  albumCached: (id) => isCached(`albums/${id}`),
  artists: () => cached("artists"),
  search: (q) => request("GET", `search?q=${encodeURIComponent(q)}`),
  randomTracks: (artist) => request("GET", `tracks/random?limit=200${artist ? `&artist=${encodeURIComponent(artist)}` : ""}`),
  lyrics: (id) => cached(`tracks/${id}/lyrics`, 600_000),
  video: (id) => cached(`tracks/${id}/video`, 600_000),
  recommendations: (id, seed = 0, limit = 10) => request("GET", `playlists/${id}/recommendations?seed=${seed}&limit=${limit}`),
  artist: (name) => request("GET", `artist?name=${encodeURIComponent(name)}`),
  artistAbout: (name) => cached(`artist/about?name=${encodeURIComponent(name)}`, 3_600_000),
  artistVideos: (name) => cached(`artist/videos?name=${encodeURIComponent(name)}`, 3_600_000),
  playlists: () => cached("playlists", 5_000),
  playlist: (id) => request("GET", `playlists/${id}`).catch((e) => savedOr(e, `playlist:${id}`)),
  createPlaylist: (body = {}) => changed(request("POST", "playlists", body)),
  previewRules: (rules) => request("POST", "smart/preview", { rules }),
  parties: () => request("GET", "parties"),
  startParty: () => request("POST", "party"),
  endParty: () => request("DELETE", "party"),
  party: (host) => request("GET", `party/${host}`),
  joinParty: (host) => request("POST", `party/${host}/join`),
  leaveParty: (host) => request("POST", `party/${host}/leave`),
  partyAdd: (host, trackIds) => request("POST", `party/${host}/add`, { trackIds }),
  partySkip: (host) => request("POST", `party/${host}/skip`),
  stats: (period = "year") => request("GET", `stats?period=${encodeURIComponent(period)}&tz=${-new Date().getTimezoneOffset()}`),
  makePlaylist: (prompt, size = 30) => request("POST", "playlists/make", { prompt, size }),
  importPlaylists: (text, filename = "") => request("POST", "playlists/import", { text, filename }),
  editPlaylist: (id, body) => changed(request("PATCH", `playlists/${id}`, body)),
  deletePlaylist: (id) => changed(request("DELETE", `playlists/${id}`)),
  addToPlaylist: (id, trackIds, { suggested = false } = {}) => changed(request("POST", `playlists/${id}/tracks`, { trackIds, suggested })),
  skipped: (id) => request("POST", `tracks/${id}/skipped`).catch(() => {}),
  makeShare: (kind, id, days) => request("POST", "shares", { kind, id, days }),
  myShares: () => request("GET", "shares"),
  stopShare: (token) => request("DELETE", `shares/${encodeURIComponent(token)}`),
  setSharing: (enabled) => request("PATCH", "admin/shares", { enabled }),
  adminSecure: () => request("GET", "admin/secure"),
  webhooks: () => request("GET", "admin/webhooks"),
  addWebhook: (body) => request("POST", "admin/webhooks", body),
  testWebhook: (id) => request("POST", `admin/webhooks/${id}/test`),
  removeWebhook: (id) => request("DELETE", `admin/webhooks/${id}`),
  setSecure: (url) => request("PUT", "admin/secure", { url }),
  setFunnel: (on) => request("POST", "admin/secure/tailscale", { on }),
  resumeAt: (id) => request("GET", `tracks/${id}/resume`),
  keepPlace: (id, position) => request("PUT", `tracks/${id}/resume`, { position: Math.max(0, position) }).catch(() => {}),
  removeFromPlaylist: (id, entryId) => changed(request("DELETE", `playlists/${id}/tracks/${entryId}`)),
  reorderPlaylist: (id, entryIds) => changed(request("PUT", `playlists/${id}/order`, { entryIds })),
  similar: (id) => request("GET", `tracks/${id}/similar?limit=40`),
  setTransition: (pid, entryId, setting) => {
    const { preset = "auto", ...parts } = typeof setting === "string" ? { preset: setting } : setting;
    return request("PUT", `playlists/${pid}/tracks/${entryId}/transition`, { style: preset, ...parts });
  },
  peaks: (id, start, end) => cached(`tracks/${id}/peaks?start=${start.toFixed(2)}&end=${end.toFixed(2)}`, 3_600_000),
  suggest: (trackIds, { exclude = [], seed = 0, limit = 10 } = {}) => request("POST", "suggest", { trackIds, exclude, seed, limit }),
  recentTracks: (limit = 50) => request("GET", `tracks/recent?limit=${limit}`),
  followPlaylist: (id) => changed(request("PUT", `playlists/${id}/follow`)),
  unfollowPlaylist: (id) => changed(request("DELETE", `playlists/${id}/follow`)),
  sharedPlaylists: () => request("GET", "playlists-shared"),
  activity: () => request("GET", "activity"),
  people: () => request("GET", "people"),
  blend: (id) => request("GET", `blend/${id}`),
  editMe: (body) => request("PATCH", "me", body),
  releases: () => cached("releases", 300_000),
  requests: () => request("GET", "requests"),
  addRequest: (body) => request("POST", "requests", body),
  removeRequest: (id) => request("DELETE", `requests/${id}`),
  resolveRequest: (id, status) => request("PATCH", `requests/${id}`, { status }),
  checkReleases: () => { invalidate("releases"); return request("POST", "releases/check"); },
  cd: () => request("GET", "cd"),
  cdRead: () => request("POST", "cd/read"),
  cdRip: (body) => request("POST", "cd/rip", body),
  cdCancel: () => request("POST", "cd/cancel"),
  cdEject: () => request("POST", "cd/eject"),
  djNext: (body) => request("POST", "dj/next", body),
  djLink: (body) => request("POST", "dj/link", body),
  djPrepare: (body) => request("POST", "dj/prepare", body),
  djRequest: (body) => request("POST", "dj/request", body),
  djFeedback: (body) => request("POST", "dj/feedback", body),
  djInstall: (model) => request("POST", `dj/builtin/${model}`),
  djNatural: () => request("POST", "dj/natural"),
  djRemove: (model) => request("DELETE", `dj/builtin/${model}`),
  djSettings: () => request("GET", "dj/settings"),
  editDjSettings: (body) => request("PATCH", "dj/settings", body),
  djSample: () => request("POST", "dj/sample"),
  mixes: () => request("GET", "mixes"),
  mix: (key) => request("GET", `mixes/${encodeURIComponent(key)}`),
  radio: (kind, value) => request("GET", `radio?${kind}=${encodeURIComponent(value)}`),
  likes: () => request("GET", "likes").catch((e) => savedOr(e, "liked")),
  folders: () => request("GET", "folders"),
  browseFolders: (path) => request("GET", `folders/browse${path ? `?path=${encodeURIComponent(path)}` : ""}`),
  addFolder: (path, replace = null) => { invalidate(); return request("POST", "folders", { path, replace }); },
  removeFolder: (path) => { invalidate(); return request("DELETE", `folders?path=${encodeURIComponent(path)}`); },
  likedIds: () => request("GET", "likes/ids"),
  like: (id) => request("PUT", `likes/${id}`),
  unlike: (id) => request("DELETE", `likes/${id}`),
  clearHistory: () => request("DELETE", "history"),
  storage: () => request("GET", "storage"),
  clearStorage: () => request("POST", "storage/clear"),
  // Offline listens are kept and sent later, with when they happened.
  played: (id) => request("POST", `tracks/${id}/played`).catch((e) => { if (e.status === 0) return offline.queuePlay(id); }),
  playedAt: (id, at) => request("POST", `tracks/${id}/played?at=${at}`),
  streamUrl: (id, q) => `api/tracks/${id}/stream?q=${q}`,
};
