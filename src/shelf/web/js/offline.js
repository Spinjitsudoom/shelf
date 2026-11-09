// Downloads: albums, playlists and Favourites saved on this device, to play with no
// connection.
//
// Everything lives in IndexedDB (it works over plain http, where service workers don't):
//   tracks       { id, blob, size, quality, track, savedAt }   one per downloaded song
//   collections  { key, kind, id, title, sub, data, trackIds, savedAt }
//                key is "album:12", "playlist:3" or "liked"; data is what the server sent
//                for that page, so it can be shown offline
//   covers       { albumId, version, blob }
//   plays        { trackId, at }                                listens made offline
//
// A song shared by two downloaded collections is stored once, and goes when neither has it.
// Downloads carry on after a reload: missing songs of every collection are queued at start.

// No imports: util.js uses this for cover art, so importing the app's modules here would loop.

const DB_NAME = "shelf-offline";
const COVER_SIZE = 640;

let db = null;
const urls = new Map(); // track id -> object URL
const coverUrls = new Map(); // album id -> object URL
const collections = new Map(); // key -> collection (without blobs)
const queue = []; // { track, tries }
const failed = new Set();
let pumping = false;
let current = null; // { id, received, total } while a song downloads
let qualityOf = () => "veryhigh"; // set by main.js from Settings

function open() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => {
      const d = req.result;
      d.createObjectStore("tracks", { keyPath: "id" });
      d.createObjectStore("collections", { keyPath: "key" });
      d.createObjectStore("covers", { keyPath: "albumId" });
      d.createObjectStore("plays", { autoIncrement: true });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function tx(store, mode, fn) {
  return new Promise((resolve, reject) => {
    const t = db.transaction(store, mode);
    const s = t.objectStore(store);
    let out;
    Promise.resolve(fn(s)).then((v) => { out = v; });
    t.oncomplete = () => resolve(out);
    t.onerror = () => reject(t.error);
    t.onabort = () => reject(t.error || new Error("Storage is full"));
  });
}

const reqP = (r) => new Promise((resolve, reject) => { r.onsuccess = () => resolve(r.result); r.onerror = () => reject(r.error); });

function each(store, fn) {
  return tx(store, "readonly", (s) => new Promise((resolve) => {
    const c = s.openCursor();
    c.onsuccess = () => {
      const cur = c.result;
      if (!cur) return resolve();
      fn(cur.value);
      cur.continue();
    };
  }));
}

const emit = (key = null) => window.dispatchEvent(new CustomEvent("downloads-changed", { detail: { key } }));

/** The bits of a track worth keeping (no blobs, nothing big). */
const slim = (t) => ({
  id: t.id, title: t.title, artist: t.artist, album: t.album, albumId: t.albumId, albumArtist: t.albumArtist,
  cover: t.cover, duration: t.duration, trackNo: t.trackNo, discNo: t.discNo, year: t.year,
  lufs: t.lufs, peak: t.peak, albumLufs: t.albumLufs, albumPeak: t.albumPeak, codec: t.codec, bpm: t.bpm, camelot: t.camelot,
});

const ready = (async () => {
  if (!("indexedDB" in window)) return;
  try {
    db = await open();
    await each("collections", (c) => collections.set(c.key, c));
    await each("tracks", (t) => urls.set(t.id, URL.createObjectURL(t.blob)));
    await each("covers", (c) => coverUrls.set(c.albumId, URL.createObjectURL(c.blob)));
  } catch (e) {
    console.warn("Downloads unavailable:", e);
    db = null;
    return;
  }
  for (const c of collections.values()) enqueue(tracksOf(c));
  pump();
})();

function tracksOf(c) {
  const list = c.kind === "liked" ? c.data : c.data?.tracks;
  return Array.isArray(list) ? list : [];
}

function enqueue(tracks) {
  for (const t of tracks) {
    if (!urls.has(t.id) && !queue.some((j) => j.track.id === t.id)) queue.push({ track: t, tries: 0 });
  }
}

async function saveCover(albumId, version) {
  if (!albumId || !version || coverUrls.has(albumId)) return;
  try {
    const res = await fetch(`api/albums/${albumId}/cover?size=${COVER_SIZE}&v=${version}`, { credentials: "same-origin" });
    if (!res.ok) return;
    const blob = await res.blob();
    await tx("covers", "readwrite", (s) => s.put({ albumId, version, blob }));
    coverUrls.set(albumId, URL.createObjectURL(blob));
  } catch { /* covers are nice to have */ }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function pump() {
  if (pumping || !db) return;
  pumping = true;
  try {
    while (queue.length) {
      if (!navigator.onLine) { await sleep(5000); continue; }
      const job = queue[0];
      const t = job.track;
      if (urls.has(t.id) || !wanted(t.id)) { queue.shift(); continue; }
      const quality = qualityOf() || "veryhigh";
      current = { id: t.id, received: 0, total: 0 };
      emit();
      try {
        const res = await fetch(`api/tracks/${t.id}/stream?q=${quality}`, { credentials: "same-origin" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        current.total = Number(res.headers.get("content-length")) || 0;
        const reader = res.body.getReader();
        const parts = [];
        let lastEmit = 0;
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          parts.push(value);
          current.received += value.length;
          if (performance.now() - lastEmit > 400) { lastEmit = performance.now(); emit(); }
        }
        const blob = new Blob(parts, { type: res.headers.get("content-type") || "audio/mp4" });
        await tx("tracks", "readwrite", (s) => s.put({ id: t.id, blob, size: blob.size, quality, track: slim(t), savedAt: Date.now() }));
        urls.set(t.id, URL.createObjectURL(blob));
        failed.delete(t.id);
        queue.shift();
        await saveCover(t.albumId, t.cover);
      } catch (e) {
        if (String(e).includes("full") || e?.name === "QuotaExceededError") {
          queue.length = 0;
          window.dispatchEvent(new CustomEvent("downloads-full"));
          break;
        }
        job.tries++;
        queue.shift();
        if (job.tries < 3) queue.push(job);
        else failed.add(t.id);
        await sleep(2000);
      } finally {
        current = null;
        emit();
      }
    }
  } finally {
    pumping = false;
  }
}

/** True if some downloaded collection still wants this song. */
function wanted(id) {
  for (const c of collections.values()) if (c.trackIds.includes(id)) return true;
  return false;
}

/** Delete songs and covers no collection uses any more. */
async function cleanUp() {
  const keep = new Set();
  const albums = new Set();
  for (const c of collections.values()) {
    for (const t of tracksOf(c)) { keep.add(t.id); albums.add(t.albumId); }
  }
  const dropTracks = [...urls.keys()].filter((id) => !keep.has(id));
  const dropCovers = [...coverUrls.keys()].filter((id) => !albums.has(id));
  if (dropTracks.length) {
    await tx("tracks", "readwrite", (s) => { for (const id of dropTracks) s.delete(id); });
    for (const id of dropTracks) { URL.revokeObjectURL(urls.get(id)); urls.delete(id); }
  }
  if (dropCovers.length) {
    await tx("covers", "readwrite", (s) => { for (const id of dropCovers) s.delete(id); });
    for (const id of dropCovers) { URL.revokeObjectURL(coverUrls.get(id)); coverUrls.delete(id); }
  }
}

function describe(kind, data) {
  if (kind === "album") return { title: data.title, sub: data.artist };
  if (kind === "playlist") return { title: data.name, sub: "Playlist" };
  return { title: "Favourites", sub: "Playlist" };
}

export const offline = {
  ready,
  /** Where the download quality comes from (Settings). */
  setQuality(fn) { qualityOf = fn; },
  get available() { return !!db; },

  has: (trackId) => urls.has(trackId),
  url: (trackId) => urls.get(trackId) ?? null,
  coverUrl: (albumId) => coverUrls.get(albumId) ?? null,
  count: () => urls.size,

  isSaved: (key) => collections.has(key),
  /** What the page sent for this collection when it was last saved (album, playlist or liked list). */
  data: (key) => collections.get(key)?.data ?? null,
  list: () => [...collections.values()].sort((a, b) => b.savedAt - a.savedAt),

  /** { saved, done, total, downloading, progress 0..1 } for a collection's download button. */
  state(key) {
    const c = collections.get(key);
    if (!c) return { saved: false, done: 0, total: 0, downloading: false, progress: 0 };
    const total = c.trackIds.length;
    let done = 0;
    for (const id of c.trackIds) if (urls.has(id)) done++;
    const waiting = c.trackIds.some((id) => !urls.has(id) && !failed.has(id));
    let partial = 0;
    if (current && c.trackIds.includes(current.id) && current.total) partial = current.received / current.total;
    return { saved: true, done, total, downloading: waiting, failed: c.trackIds.filter((id) => failed.has(id)).length,
      progress: total ? Math.min(1, (done + partial) / total) : 1 };
  },

  /** Download a collection (or update a downloaded one with fresh data from the server). */
  async save(kind, id, data) {
    await ready;
    if (!db) throw new Error("This browser can’t store downloads");
    const key = kind === "liked" ? "liked" : `${kind}:${id}`;
    const tracks = kind === "liked" ? data : data.tracks;
    const c = {
      key, kind, id, ...describe(kind, data), data,
      trackIds: tracks.map((t) => t.id),
      savedAt: collections.get(key)?.savedAt ?? Date.now(),
    };
    await tx("collections", "readwrite", (s) => s.put(c));
    collections.set(key, c);
    enqueue(tracks);
    await cleanUp();
    emit(key);
    if (navigator.storage?.persist) navigator.storage.persist().catch(() => {});
    pump();
    return key;
  },

  /** Keep a downloaded collection in step with the server (songs added or removed). */
  async refresh(key, data) {
    const c = collections.get(key);
    if (!c) return;
    const tracks = c.kind === "liked" ? data : data.tracks;
    const same = tracks.length === c.trackIds.length && tracks.every((t, i) => t.id === c.trackIds[i]);
    if (same) return;
    await offline.save(c.kind, c.id, data);
  },

  async remove(key) {
    await ready;
    if (!collections.has(key)) return;
    await tx("collections", "readwrite", (s) => s.delete(key));
    collections.delete(key);
    await cleanUp();
    emit(key);
  },

  async removeAll() {
    await ready;
    if (!db) return;
    queue.length = 0;
    for (const store of ["collections", "tracks", "covers"]) await tx(store, "readwrite", (s) => s.clear());
    for (const u of urls.values()) URL.revokeObjectURL(u);
    for (const u of coverUrls.values()) URL.revokeObjectURL(u);
    urls.clear(); coverUrls.clear(); collections.clear(); failed.clear();
    emit("*");
  },

  /** Bytes used by downloaded songs and covers. */
  async usage() {
    await ready;
    if (!db) return 0;
    let bytes = 0;
    await each("tracks", (t) => { bytes += t.size || 0; });
    return bytes;
  },

  /** Downloaded songs, for the Downloads page when offline. */
  async tracks() {
    await ready;
    const out = [];
    if (db) await each("tracks", (t) => out.push(t.track));
    return out;
  },

  get busy() { return queue.length > 0; },
  get pending() { return queue.length; },

  // ---- listens made offline ----

  async queuePlay(trackId) {
    await ready;
    if (db) await tx("plays", "readwrite", (s) => s.add({ trackId, at: Date.now() / 1000 }));
  },

  /** Send listens made offline (oldest first) with `send(trackId, at)`. */
  async flushPlays(send) {
    await ready;
    if (!db) return 0;
    const rows = await tx("plays", "readonly", (s) => Promise.all([reqP(s.getAllKeys()), reqP(s.getAll())]));
    const [keys, values] = rows;
    let sent = 0;
    for (let i = 0; i < keys.length; i++) {
      try {
        await send(values[i].trackId, values[i].at);
      } catch (e) {
        if (e.status === 0) break; // offline again: try later
      }
      await tx("plays", "readwrite", (s) => s.delete(keys[i]));
      sent++;
    }
    return sent;
  },

  /** Try failed songs again (e.g. when the connection comes back). */
  retry() {
    for (const c of collections.values()) {
      for (const t of tracksOf(c)) failed.delete(t.id);
      enqueue(tracksOf(c));
    }
    pump();
  },
};

window.addEventListener("online", () => offline.retry());
