// "Your Library": the left-hand panel on wider screens. Playlists, albums and artists in one list,
// with filter chips, a sort menu, a quick filter, and the playing album marked. Once you follow
// artists it holds just them and their albums (the sort menu can still show everything);
// until then it shows the whole shelf.

import { api, invalidate } from "./api.js";
import { openMenu } from "./menu.js";
import { likes } from "./likes.js";
import { offline } from "./offline.js";
import { caseHtml, esc, playlistCover, plural, store } from "./util.js";
import { artistHref, likedCover } from "./views.js";

const SORTS = {
  recent: "Recents",
  added: "Recently added",
  alpha: "Alphabetical",
  creator: "Creator",
};
const FILTERS = { playlists: "Playlists", albums: "Albums", artists: "Artists", downloaded: "Downloaded" };

const fold = (s) => (s || "").normalize("NFKD").replace(/\p{M}/gu, "").toLocaleLowerCase();
const byText = (a, b) => a.localeCompare(b, undefined, { sensitivity: "base", numeric: true });

export function mountLibrary(root, player) {
  const list = root.querySelector("#lib-list");
  const chips = root.querySelector("#lib-chips");
  const search = root.querySelector("#lib-search");
  const searchWrap = root.querySelector("#lib-search-wrap");
  const sortBtn = root.querySelector("#lib-sort");
  let filter = store.get("libFilter", null);
  let sort = store.get("libSort", "recent");
  let everything = !!store.get("libEverything", false);
  let follows = new Set();
  let query = "";
  let albums = [], artists = [], playlists = [];

  let loading = Promise.resolve();
  function load() {
    loading = loadNow();
    return loading;
  }

  async function loadNow() {
    try {
      [albums, artists, playlists] = await Promise.all([api.albums("recent"), api.artists(), api.playlists()]);
    } catch (e) {
      if (e.status !== 0) return;
      // Offline: what's downloaded.
      await offline.ready;
      const saved = offline.list();
      albums = saved.filter((c) => c.kind === "album").map((c) => ({ ...c.data, addedAt: c.savedAt / 1000 }));
      playlists = saved.filter((c) => c.kind === "playlist").map((c) => ({ ...c.data, updatedAt: c.savedAt / 1000 }));
      artists = [];
    }
    // An artist is as recent as their most recently played or added album.
    const recency = new Map();
    for (const a of albums) {
      const key = fold(a.artist);
      const t = Math.max(a.lastPlayed || 0, a.addedAt || 0);
      recency.set(key, Math.max(recency.get(key) || 0, t));
    }
    for (const ar of artists) ar.recency = recency.get(fold(ar.name)) || 0;
    follows = new Set(artists.filter((ar) => ar.following).map((ar) => fold(ar.name)));
    draw();
  }

  /** Just what you follow: on once you follow someone, unless the sort menu says everything. */
  const tidy = () => follows.size > 0 && !everything;
  const followedAlbum = (a) => (a.artists?.length ? a.artists : [a.artist]).some((n) => follows.has(fold(n)));

  function items() {
    const out = [];
    const only = tidy();
    const dl = filter === "downloaded";
    if (!filter || filter === "playlists" || dl) {
      for (const p of playlists) {
        if (!dl || offline.isSaved(`playlist:${p.id}`)) out.push({ kind: "playlist", p, name: p.name, by: "", added: p.createdAt, recent: p.updatedAt });
      }
    }
    if (!filter || filter === "albums" || dl) {
      for (const a of albums) {
        if (dl && !offline.isSaved(`album:${a.id}`)) continue;
        if (only && !dl && !followedAlbum(a)) continue;
        out.push({ kind: "album", a, name: a.title, by: a.artist, added: a.addedAt || 0, recent: Math.max(a.lastPlayed || 0, a.addedAt || 0) });
      }
    }
    if (!filter || filter === "artists") {
      for (const ar of artists) if (!only || ar.following) out.push({ kind: "artist", ar, name: ar.name, by: ar.name, added: ar.recency, recent: ar.recency });
    }
    const q = fold(query.trim());
    const shown = q ? out.filter((it) => fold(it.name).includes(q) || fold(it.by).includes(q)) : out;
    const cmp = {
      recent: (x, y) => y.recent - x.recent || byText(x.name, y.name),
      added: (x, y) => y.added - x.added || byText(x.name, y.name),
      alpha: (x, y) => byText(x.name, y.name),
      creator: (x, y) => byText(x.by, y.by) || (x.kind === "artist" ? -1 : y.kind === "artist" ? 1 : byText(x.name, y.name)),
    }[sort];
    shown.sort(cmp);
    // Favourites stays pinned at the top.
    if ((!filter || filter === "playlists" || (dl && offline.isSaved("liked"))) && (!q || fold("favourites").includes(q))) shown.unshift({ kind: "liked" });
    return shown;
  }

  const dlMark = (key) => offline.isSaved(key) ? `<svg class="lib-dl" aria-label="Downloaded"><use href="#i-downloaded"/></svg>` : "";

  function itemHtml(it) {
    if (it.kind === "liked") {
      return `
        <a class="lib-item" role="listitem" href="#/liked" title="Favourites">
          ${likedCover()}
          <span class="lib-text"><span class="lib-name">Favourites</span><span class="lib-sub">${dlMark("liked")}<svg class="lib-pin" aria-label="Pinned"><use href="#i-pin"/></svg>Playlist • ${plural(likes.count, "song")}</span></span>
          <svg class="lib-playing" aria-label="Playing"><use href="#i-volume"/></svg>
        </a>`;
    }
    if (it.kind === "playlist") {
      const p = it.p;
      return `
        <a class="lib-item" role="listitem" href="#/playlist/${p.id}" data-playlist="${p.id}" title="${esc(p.name)}">
          ${playlistCover(p, { cls: "lib-cover" })}
          <span class="lib-text"><span class="lib-name">${esc(p.name)}</span><span class="lib-sub">${dlMark(`playlist:${p.id}`)}Playlist • ${p.mine === false ? esc(p.owner?.username ?? "") : plural(p.trackCount, "song")}</span></span>
          <svg class="lib-playing" aria-label="Playing"><use href="#i-volume"/></svg>
        </a>`;
    }
    if (it.kind === "album") {
      const a = it.a;
      return `
        <a class="lib-item" role="listitem" href="#/album/${a.id}" data-album="${a.id}" data-artist="${esc(a.artist)}" data-artists="${esc(JSON.stringify(a.artists ?? [a.artist]))}" data-title="${esc(a.title)}" title="${esc(a.title)}">
          ${caseHtml(a, { size: 160, cls: "case-sm", sizes: "48px" })}
          <span class="lib-text"><span class="lib-name">${esc(a.title)}</span><span class="lib-sub">${dlMark(`album:${a.id}`)}Album • ${esc(a.artist)}</span></span>
          <svg class="lib-playing" aria-label="Playing"><use href="#i-volume"/></svg>
        </a>`;
    }
    const ar = it.ar;
    return `
      <a class="lib-item lib-artist" role="listitem" href="${artistHref(ar.name)}" data-artist-name="${esc(ar.name)}" data-following="${!!ar.following}" title="${esc(ar.name)}">
        ${caseHtml({ id: ar.coverAlbumId, cover: ar.cover, title: ar.name }, { size: 160, cls: "case-sm", sizes: "48px" })}
        <span class="lib-text"><span class="lib-name">${esc(ar.name)}</span><span class="lib-sub">Artist</span></span>
        <svg class="lib-playing" aria-label="Playing"><use href="#i-volume"/></svg>
      </a>`;
  }

  function drawChips() {
    chips.innerHTML = filter
      ? `<button class="chip chip-clear" type="button" data-filter="" aria-label="Clear filter"><svg><use href="#i-close"/></svg></button>
         <button class="chip" type="button" data-filter="${filter}" aria-pressed="true">${FILTERS[filter]}</button>`
      : Object.entries(FILTERS).map(([k, v]) => `<button class="chip" type="button" data-filter="${k}" aria-pressed="false">${v}</button>`).join("");
    root.querySelector("#lib-sort-label").textContent = SORTS[sort];
  }

  function hint() {
    if (query || filter === "playlists" || filter === "downloaded" || !artists.length) return "";
    if (!follows.size) return `<p class="lib-hint">Follow the artists you like and this list keeps to them and their albums.</p>`;
    return "";
  }

  function draw() {
    drawChips();
    const all = items();
    const empty = query ? `Nothing in your library matches “${esc(query)}”.`
      : tidy() ? "Nothing here from the artists you follow."
      : "Your library is empty. Add music folders in config.toml.";
    list.innerHTML = hint() + (all.length ? all.map(itemHtml).join("") : `<p class="lib-empty">${empty}</p>`);
    markPlaying();
    markCurrent();
  }

  function markPlaying() {
    const t = player.current;
    const artist = t ? fold(t.albumArtist || t.artist) : null;
    list.querySelectorAll(".lib-item").forEach((el) => {
      const href = el.getAttribute("href");
      const on = !!t && (el.dataset.playlist || href === "#/liked" ? player.context?.href === href : Number(el.dataset.album) === t.albumId || (!!el.dataset.artistName && fold(el.dataset.artistName) === artist));
      el.classList.toggle("is-playing", on);
      el.classList.toggle("is-paused", on && !player.playing);
    });
  }

  function markCurrent() {
    const here = location.hash.split("?")[0];
    list.querySelectorAll(".lib-item").forEach((el) => el.classList.toggle("is-here", el.getAttribute("href") === here));
  }

  chips.addEventListener("click", (e) => {
    const b = e.target.closest("[data-filter]");
    if (!b) return;
    filter = filter === b.dataset.filter || !b.dataset.filter ? null : b.dataset.filter;
    store.set("libFilter", filter);
    draw();
    list.scrollTop = 0;
  });

  sortBtn.addEventListener("click", () => {
    openMenu({
      at: sortBtn,
      heading: "Sort and show",
      items: [
        ...Object.entries(SORTS).map(([k, label]) => ({
          label, icon: k === sort ? "i-check" : "i-sort", current: k === sort,
          run: () => { sort = k; store.set("libSort", k); draw(); list.scrollTop = 0; },
        })),
        "sep",
        ...[[false, "What you follow", follows.size ? `${plural(follows.size, "artist")} and their albums` : "Follow an artist from their page"],
          [true, "Everything on the server", null]].map(([all, label, sub]) => ({
          label, sub, icon: all === everything ? "i-check" : "i-library", current: all === everything,
          run: () => { everything = all; store.set("libEverything", all); draw(); list.scrollTop = 0; },
        })),
      ],
    });
  });

  root.querySelector("#lib-search-btn").addEventListener("click", () => {
    searchWrap.classList.add("open");
    search.focus();
  });
  search.addEventListener("input", () => { query = search.value; draw(); });
  search.addEventListener("blur", () => { if (!search.value) searchWrap.classList.remove("open"); });
  search.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { search.value = ""; query = ""; draw(); search.blur(); }
  });

  // Collapse to a strip of covers, like a closed library sidebar.
  const app = document.getElementById("app");
  const setCollapsed = (on) => {
    app.classList.toggle("lib-collapsed", on);
    store.set("libCollapsed", on);
    const btn = root.querySelector("#lib-collapse");
    const label = on ? "Expand your library" : "Collapse your library";
    btn.setAttribute("aria-label", label);
    btn.title = label;
  };
  setCollapsed(!!store.get("libCollapsed", false));
  root.querySelector("#lib-collapse").addEventListener("click", () => setCollapsed(!app.classList.contains("lib-collapsed")));

  player.addEventListener("track", markPlaying);
  player.addEventListener("state", markPlaying);
  player.addEventListener("played", () => { invalidate("albums?sort=recent"); load(); });
  window.addEventListener("playlists-changed", () => load());
  window.addEventListener("follows-changed", () => load());

  // "+": a new, empty playlist, opened right away .
  root.querySelector("#lib-new").addEventListener("click", async () => {
    const p = await api.createPlaylist();
    location.hash = `#/playlist/${p.id}`;
  });
  addEventListener("hashchange", markCurrent);

  load();
  return {
    refresh: () => { invalidate("albums"); invalidate("artists"); load(); },
    redraw: () => draw(),
    /** Settles when the library has finished its latest redraw. */
    get loading() { return loading; },
  };
}
