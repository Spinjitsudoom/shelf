// Keeps the app shell available offline and quick to open. Never caches /api (music, covers
// and library data always come live from the server).
const CACHE = "shelf-shell-v72";
const SHELL = ["./", "style.css", "js/main.js", "js/api.js", "js/player.js", "js/views.js", "js/util.js", "js/menu.js", "js/settings.js", "js/audio.js", "js/mixer.js", "js/connect.js", "js/lyrics.js", "js/library.js", "js/npv.js", "js/video.js", "js/likes.js", "js/transitions.js", "js/transition-editor.js", "js/server.js", "js/admin.js", "js/native.js", "js/offline.js", "js/sleep.js",
  "js/smart.js", "js/resume.js", "js/sharelinks.js", "js/whatsnew.js", "js/secure.js", "js/importer.js", "js/webhooks.js", "js/queuedrag.js", "js/requests.js", "js/podcasts.js", "js/dj.js", "js/party.js", "js/visualizer.js", "sounds/sting.m4a", "fonts/fonts.css", "fonts/archivo-latin.woff2", "fonts/caveat-latin.woff2",
  "manifest.webmanifest", "icons/icon.svg", "icons/icon-192.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || url.pathname.includes("/api/")) return;
  // Network first so updates show immediately; fall back to the cached shell when offline.
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        if (res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy));
        }
        return res;
      })
      .catch(() => caches.match(e.request).then((r) => r || caches.match("./"))),
  );
});
