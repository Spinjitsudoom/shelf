// App entry: sign-in, routing (with cover-morph page transitions), the player bar and
// now-playing screen, quick-action menus, and global shortcuts.

import { api, invalidate, isOffline, setUnauthorizedHandler } from "./api.js";
import { Controller } from "./connect.js";
import { mountLibrary } from "./library.js";
import { likes, refreshAll as refreshHearts } from "./likes.js";
import { mountTransitionEditor } from "./transition-editor.js";
import { mountLyrics } from "./lyrics.js";
import { mountPanel } from "./npv.js";
import { VideoMode } from "./video.js";
import { closeMenu, menuOpen, openMenu } from "./menu.js";
import { mountMixer } from "./mixer.js";
import { adminView } from "./admin.js";
import { settings } from "./settings.js";
import { Player } from "./player.js";
import { nativeApp as android, currentServer, switchServer } from "./server.js";
import { manageLinks, shareLink } from "./sharelinks.js";
import { maybeShowWhatsNew, showWhatsNew } from "./whatsnew.js";
import { clearNative, mountNative } from "./native.js";
import { mountSleep } from "./sleep.js";
import { mountDJ } from "./dj.js";
import { follow as followHost } from "./party.js";
import { startRing } from "./visualizer.js";
import { editRules } from "./smart.js";
import { applyAlbumColor, caseHtml, coverUrl, esc, fmtTime, playlistCover, plural, quality, store, toast } from "./util.js";
import {
  albumView, albumsView, artistHref, artistItems, artistLinks, artistView, artistsView, balanceLabel, ctx, homeView, mixerView,
  partyView, playlistView, playlistsView, queueView, statsView, wrappedView, wrappedStep, refreshRecommendations, refreshSettings, searchView, settingsView, skeleton,
  videoCard, youTubeOnly, youTubeOnlyList, likedView, downloadsView, refreshDownloads, mixView, peopleView, releasesView, personDisc,
  features,
} from "./views.js";
import { offline } from "./offline.js";
import { claimHandoff, moveToSecure } from "./secure.js";

const $ = (id) => document.getElementById(id);
const view = $("view");
// `local` plays music on this device; `player` is what the interface talks to: it passes
// through to `local`, or remote-controls another device when that one is playing.
const local = new Player($("audio-a"), $("audio-b"));
const player = new Controller(local);
// A page shown inside another app (the Android app's admin dashboard): just the page, no player,
// tabs or library, and not one of your devices.
const embedded = new URLSearchParams(location.search).has("embed");
if (embedded) document.documentElement.classList.add("embedded");
const session = { user: null };
const canMorph = typeof document.startViewTransition === "function";
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
if (new URLSearchParams(location.search).has("debug")) window.shelfDebug = { player, local, settings, get video() { return video; } };

// ---------- theme ----------

function applyTheme(theme, resync = true) {
  if (theme === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
  if (resync) syncPlayer(); // album accent colors depend on light/dark
}
applyTheme(store.get("theme", "system"), false);

const applyDisplay = () => {
  document.body.classList.toggle("no-spin", !settings.get("spinDisc"));
  document.body.classList.toggle("vinyl", settings.get("shelfFormat") === "vinyl");
};
applyDisplay();
settings.onChange((patch) => { if ("spinDisc" in patch || "shelfFormat" in patch) applyDisplay(); });

// ---------- routing ----------

const scrollMemory = new Map();
let currentKey = null;
let albumOnScreen = null; // id of the album page being shown, for the cover morph back out
let clickedCase = null; // the cover that was just clicked, so the morph starts from it
let firstRender = true;

function parseRoute() {
  const hash = location.hash.replace(/^#/, "") || "/";
  const [path, query = ""] = hash.split("?");
  const params = new URLSearchParams(query);
  const parts = path.split("/").filter(Boolean);
  switch (parts[0]) {
    case undefined: return { name: "home", nav: "home" };
    case "albums": return { name: "albums", sort: params.get("sort"), nav: "albums" };
    case "album": return { name: "album", id: Number(parts[1]), nav: "albums" };
    case "artists": return { name: "artists", nav: "artists" };
    case "artist": return { name: "artist", artist: decodeURIComponent(parts.slice(1).join("/")), nav: "artists" };
    case "search": return { name: "search", q: params.get("q") || "", nav: "search" };
    case "queue": return { name: "queue", nav: "queue" };
    case "settings": return { name: "settings", nav: "settings" };
    case "admin": return { name: "admin", nav: "admin" };
    case "mixer": return { name: "mixer", nav: "settings" };
    case "lyrics": return { name: "lyrics", nav: "lyrics" };
    case "playlists": return { name: "playlists", nav: "playlists" };
    case "liked": return { name: "liked", nav: "playlists" };
    case "downloads": return { name: "downloads", nav: "playlists" };
    case "mix": return { name: "mix", key: parts[1], nav: "home" };
    case "blend": return { name: "mix", blend: Number(parts[1]), nav: "people" };
    case "people": return { name: "people", nav: "people" };
    case "party": return { name: "party", host: Number(parts[1]), nav: "people" };
    case "stats": return { name: "stats", period: params.get("period") || "year", nav: "stats" };
    case "wrapped": return { name: "wrapped", year: Number(parts[1]) || new Date().getFullYear(), nav: "stats" };
    case "releases": return { name: "releases", nav: "home" };
    case "radio": return { name: "mix", radio: parts[1] === "artist" ? "artist" : "track", value: decodeURIComponent(parts.slice(2).join("/")), nav: "home" };
    case "playlist": return { name: "playlist", id: Number(parts[1]), nav: "playlists" };
    default: return { name: "home", nav: "home" };
  }
}

let unmountPage = null; // pages with live parts (the mixer) clean up when left

async function drawRoute(route, key) {
  unmountPage?.();
  unmountPage = null;
  document.querySelectorAll("[data-nav]").forEach((a) => {
    if (a.dataset.nav === route.nav) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  applyAlbumColor(view, null);
  try {
    switch (route.name) {
      case "home": if (isOffline) await downloadsView(view); else await homeView(view, player); break;
      case "downloads": await downloadsView(view); break;
      case "mix": await mixView(view, route); unmountPage = albumStickyHead(); break;
      case "releases": {
        await releasesView(view, { admin: !!session.user?.admin });
        // While MusicBrainz is being checked, follow along (and show the result when it's done).
        const timer = setInterval(async () => {
          if (parseRoute().name !== "releases" || document.hidden) return;
          const wasRunning = !!view.querySelector(".releases-page[data-running]");
          invalidate("releases");
          const r = await api.releases().catch(() => null);
          if (r && (r.state?.running || wasRunning)) await releasesView(view, { admin: !!session.user?.admin }).catch(() => {});
        }, 3000);
        unmountPage = () => clearInterval(timer);
        break;
      }
      case "people": {
        await peopleView(view);
        // Keep it live while it's open.
        const timer = setInterval(() => {
          if (!document.hidden && parseRoute().name === "people") peopleView(view).catch(() => {});
        }, 20000);
        unmountPage = () => clearInterval(timer);
        break;
      }
      case "albums": await albumsView(view, route.sort); break;
      case "album": await albumView(view, route.id); unmountPage = albumStickyHead(); break;
      case "artists": await artistsView(view); break;
      case "artist": {
        await artistView(view, route.artist);
        const off = albumStickyHead();
        // A video playing on the page closes with it.
        unmountPage = () => { off?.(); if (video.host && !document.body.contains(video.host)) video.stop(false); };
        break;
      }
      case "search": await searchView(view, route.q); break;
      case "queue": queueView(view, player); break;
      case "settings": await settingsView(view, player, session); break;
      case "admin": unmountPage = await adminView(view, session, { dialog }); break;
      case "mixer": mixerView(view); unmountPage = mountMixer(view, local); break;
      case "lyrics": unmountPage = lyricsPage(); break;
      case "playlists": await playlistsView(view); break;
      case "stats": await statsView(view, route.period); break;
      case "party": {
        await partyView(view, route.host);
        // Keep it live while it's open (and skip a redraw while someone's typing a search).
        const timer = setInterval(() => {
          if (document.hidden || parseRoute().name !== "party" || document.activeElement?.id === "party-find") return;
          partyView(view, route.host).catch(() => {});
        }, 4000);
        unmountPage = () => clearInterval(timer);
        break;
      }
      case "wrapped": await wrappedView(view, route.year); break;
      case "liked": await likedView(view); unmountPage = albumStickyHead(); break;
      case "playlist": await playlistView(view, route.id); unmountPage = albumStickyHead(); break;
    }
  } catch (e) {
    if (e.status === 401) return;
    if (e.status === 0) {
      view.innerHTML = `<div class="page"><div class="empty"><strong>You’re offline</strong>This page needs a connection. Your downloads still play.
        <a class="btn" href="#/downloads" style="margin-top:14px"><svg><use href="#i-download"/></svg>Go to Downloads</a></div></div>`;
      return;
    }
    view.innerHTML = `<div class="page"><div class="empty"><strong>${e.status === 404 ? "This isn’t on the shelf anymore" : "Couldn’t load this page"}</strong>${esc(e.message)}. <a href="#/" style="text-decoration:underline">Go home</a></div></div>`;
  }
  refreshDownloads(view);
  addMeButton(route);
  if (route.name === "home" && !isOffline) djShow?.prepare();
  if (route.name !== "lyrics") view.scrollTop = scrollMemory.get(key) ?? 0;
  document.querySelectorAll(".route-toggle").forEach((a) => a.classList.toggle("on", a.dataset.route === route.name));
  markPlayingRow();
  const h1 = view.querySelector("h1")?.textContent;
  document.title = route.name === "home" || !h1 ? "Shelf" : `${h1} – Shelf`;
}

/** On album pages, a bar with the play button and title slides in once the big ones scroll away. */
function albumStickyHead() {
  const page = view.querySelector(".album-page");
  const actions = page?.querySelector(".album-actions");
  if (!actions) return null;
  const bar = document.createElement("div");
  bar.className = "sticky-head";
  bar.innerHTML = `<button class="sticky-play" type="button" data-action="play-list" aria-label="Play" tabindex="-1"><svg><use href="#i-play"/></svg></button>
    <span class="sticky-title">${esc(page.querySelector("h1")?.textContent ?? "")}</span>`;
  page.prepend(bar);
  const io = new IntersectionObserver(([e]) => bar.classList.toggle("show", !e.isIntersecting && e.boundingClientRect.top < 100),
    { root: view, rootMargin: "-64px 0px 0px 0px" });
  io.observe(actions);
  return () => io.disconnect();
}

/** The Lyrics page: the words fill the main view, tinted with the album's color. */
function lyricsPage() {
  view.innerHTML = `<div class="lyrics-page"><h1 class="sr-only">Lyrics</h1><div class="ly-root"></div></div>`;
  const tint = () => {
    const t = player.current;
    if (!t) return;
    api.album(t.albumId).then((a) => { if (parseRoute().name === "lyrics") applyAlbumColor(view, a.color); }).catch(() => {});
  };
  tint();
  player.addEventListener("track", tint);
  const off = mountLyrics(view.querySelector(".ly-root"), view, player);
  return () => { off(); player.removeEventListener("track", tint); };
}

/** The on-screen cover for an album: the page's big one if present, else the first visible. */
function findCase(id) {
  const all = [...view.querySelectorAll(`[data-album-case="${id}"]`)];
  const big = all.find((el) => el.closest(".album-hero, .hero"));
  if (big) return big;
  const vh = view.getBoundingClientRect();
  return all.find((el) => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.bottom > vh.top && r.top < vh.bottom;
  }) ?? null;
}

async function imageReady(el) {
  const img = el?.querySelector("img");
  if (img) await Promise.race([img.decode().catch(() => {}), new Promise((r) => setTimeout(r, 300))]);
}

async function render() {
  if (currentKey) scrollMemory.set(currentKey, view.scrollTop);
  const route = parseRoute();
  const key = location.hash.split("?")[0] || "#/";
  currentKey = key;
  closeNowPlaying(false);

  const focus = route.name === "album" ? route.id : albumOnScreen;
  albumOnScreen = route.name === "album" ? route.id : null;

  // Cover morph: the album cover you tapped grows into the album page (and back).
  if (canMorph && !reducedMotion.matches && !firstRender && focus != null) {
    const from = clickedCase?.isConnected && Number(clickedCase.dataset.albumCase) === focus ? clickedCase : findCase(focus);
    clickedCase = null;
    if (from) {
      from.style.viewTransitionName = "album-art";
      const vt = document.startViewTransition(async () => {
        from.style.viewTransitionName = "";
        await drawRoute(route, key);
        const to = findCase(focus);
        if (to) {
          to.style.viewTransitionName = "album-art";
          await imageReady(to);
        }
      });
      vt.ready.catch(() => {}); // a quicker tap skips this morph; that's fine
      vt.finished.finally(() => {
        view.querySelectorAll("[data-album-case]").forEach((el) => { el.style.viewTransitionName = ""; });
      }).catch(() => {});
      await vt.updateCallbackDone.catch(() => {});
      return;
    }
  }

  // Otherwise draw directly, with a placeholder if loading takes a moment.
  const placeholder = setTimeout(() => {
    view.innerHTML = skeleton(route.name === "album" ? "album" : "grid");
  }, 140);
  await drawRoute(route, key);
  clearTimeout(placeholder);
}

window.addEventListener("hashchange", render);

// ---------- actions (event delegation) ----------

const rowIndex = (el) => Number(el.closest("[data-index]")?.dataset.index);
let suppressClick = false;

view.addEventListener("click", (e) => {
  if (suppressClick) { e.preventDefault(); e.stopPropagation(); suppressClick = false; return; }
  const link = e.target.closest('a[href^="#/album/"]');
  if (link) clickedCase = link.querySelector("[data-album-case]") ?? link.closest(".album-card")?.querySelector("[data-album-case]") ?? null;
}, true);

// ---------- settings controls ----------

function applySetting(el) {
  const key = el.dataset.setting;
  if (key === "theme") {
    store.set("theme", el.dataset.value);
    applyTheme(el.dataset.value);
    view.querySelectorAll('[data-setting="theme"]').forEach((b) => b.setAttribute("aria-pressed", String(b === el)));
    return;
  }
  let value;
  if (el.matches(".switch")) value = !settings.get(key);
  else if (el.dataset.value !== undefined) value = el.dataset.value;
  else if (el.type === "range") {
    value = Number(el.value);
    if (key === "balance" && Math.abs(value) < 0.06) value = 0; // snap to center
  } else value = el.value;
  settings.set({ [key]: value });
  player.enableEngineIfNeeded(); // this is a tap, so the browser lets the sound engine start
  refreshSettings(view);
  if (key === "balance") {
    el.setAttribute("aria-valuetext", balanceLabel(value));
    const out = view.querySelector('[data-out="balance"]');
    if (out) out.textContent = balanceLabel(value);
  }
}

view.addEventListener("input", (e) => {
  if (e.target.matches('input[type="range"][data-setting]')) applySetting(e.target);
});
view.addEventListener("change", (e) => {
  if (e.target.matches('select[data-setting], input[type="text"][data-setting]')) applySetting(e.target);
});
view.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && e.target.matches('input[type="text"][data-setting]')) e.target.blur();
});

view.addEventListener("click", async (e) => {
  const set = e.target.closest(".switch[data-setting], button[data-setting][data-value]");
  if (set) {
    e.preventDefault();
    applySetting(set);
    return;
  }
  const btn = e.target.closest("[data-action]");
  if (btn) {
    e.preventDefault();
    e.stopPropagation();
    await runAction(btn.dataset.action, btn).catch((err) => toast(err.message));
    return;
  }
  const qrow = e.target.closest("[data-queue-index]");
  if (qrow) { player.jumpTo(Number(qrow.dataset.queueIndex)); return; }
  const row = e.target.closest(".track-row[data-index]");
  if (row && !e.target.closest("a")) player.playList(ctx.tracks, rowIndex(row), { context: ctx.context });
});

view.addEventListener("keydown", (e) => {
  if (e.key !== "Enter" && e.key !== " ") return;
  const row = e.target.closest?.(".track-row");
  if (!row || e.target !== row) return;
  e.preventDefault();
  row.click();
});

// Warm the cache when a pointer heads for an album, so it opens instantly.
const warmed = new Set();
function warm(e) {
  const a = e.target.closest?.('a[href^="#/album/"]');
  const id = a && Number(a.getAttribute("href").split("/")[2]);
  if (id && !warmed.has(id)) { warmed.add(id); api.album(id).catch(() => {}); }
}
view.addEventListener("pointerover", warm);
view.addEventListener("touchstart", warm, { passive: true });

// "Back" goes to wherever you came from inside the app, or the parent page otherwise.
let navDepth = 0;
window.addEventListener("hashchange", () => { navDepth++; });

async function runAction(action, el) {
  switch (action) {
    case "back":
      if (navDepth > 0) history.back();
      else location.hash = el.getAttribute("href");
      break;
    case "toggle": player.toggle(); break;
    case "play-album": {
      const a = await api.album(el.dataset.id);
      player.playList(a.tracks, 0, { context: { label: a.title, href: `#/album/${a.id}` } });
      break;
    }
    case "play-list": player.playList(ctx.tracks, 0, { context: ctx.context }); break;
    case "play-top": player.playList(ctx.tracks.slice(0, Number(el.dataset.count)), 0, { context: ctx.context }); break;
    case "wrapped-step": wrappedStep(view, Number(el.dataset.step)); break;
    case "party-start": {
      const me = session.user?.id;
      await api.startParty();
      toast("Your party’s on: everyone here can join from People");
      location.hash = `#/party/${me}`;
      break;
    }
    case "party-end": await api.endParty(); toast("Party’s over"); location.hash = "#/people"; break;
    case "party-leave": await api.leaveParty(parseRoute().host); store.set("party", null); location.hash = "#/people"; break;
    case "party-here": {
      const on = el.getAttribute("aria-checked") !== "true";
      store.set("party", { host: parseRoute().host, playHere: on });
      el.setAttribute("aria-checked", String(on));
      if (!on) player.pause();
      toast(on ? "Playing along here" : "Not playing here: the party plays on the host’s device");
      break;
    }
    case "party-add": {
      const host = parseRoute().host;
      const r = await api.partyAdd(host, [Number(el.dataset.track)]);
      toast(r.added ? "Added: it plays after the songs added before it" : "Couldn’t add that");
      el.disabled = true; el.textContent = "Added";
      break;
    }
    case "party-skip": {
      const r = await api.partySkip(parseRoute().host);
      toast(r.skipped ? "Skipped" : `${r.votes} of ${r.needed} votes to skip`);
      await partyView(view, parseRoute().host);
      break;
    }
    case "play-video": {
      // In the side panel when it's open, otherwise above the row of videos.
      const slot = view.querySelector("#artist-video");
      await startVideo(!$("npv").hidden ? "npv" : slot, el.dataset.video, true);
      if (slot && !slot.hidden) slot.scrollIntoView({ block: "nearest", behavior: motionOK() ? "smooth" : "auto" });
      break;
    }
    case "shuffle-list": player.playList(ctx.tracks, 0, { shuffle: true, context: ctx.context }); break;
    case "add-all": player.addToQueue(ctx.tracks); break;
    case "play-next": player.playNext([ctx.tracks[rowIndex(el)]]); break;
    case "add-queue": player.addToQueue([ctx.tracks[rowIndex(el)]]); break;
    case "menu-track": trackMenu(rowIndex(el), el); break;
    case "shuffle-all": {
      const tracks = await api.randomTracks();
      player.playList(tracks, 0, { shuffle: true, context: { label: "Everything, shuffled", href: "#/albums" } });
      break;
    }
    case "shuffle-artist": {
      const name = el.dataset.artist;
      const tracks = await api.randomTracks(name);
      player.playList(tracks, 0, { shuffle: true, context: { label: name, href: artistHref(name) } });
      break;
    }
    case "sort":
      store.set("albumSort", el.dataset.sort);
      history.replaceState(null, "", "#/albums");
      scrollMemory.delete(currentKey);
      await albumsView(view);
      view.scrollTop = 0;
      break;
    case "remove-queue": player.removeAt(Number(el.dataset.queueIndex)); break;
    case "pl-new": {
      const p = await api.createPlaylist();
      location.hash = `#/playlist/${p.id}`;
      break;
    }
    case "pl-make": {
      const made = await dialog({
        title: "Make a playlist",
        text: "Describe it, and Shelf picks songs from your library that fit.",
        fields: [{ name: "prompt", label: "What should it be?", value: "",
          hint: "A genre, artist, mood or decade, like “metal, high energy”, “chill 90s” or “like Metallica”." }],
        confirm: "Make it",
        submit: (v) => {
          if (!v.prompt.trim()) throw new Error("Describe the playlist first.");
          return api.makePlaylist(v.prompt.trim());
        },
      });
      if (!made?.trackIds) break;
      const p = await api.createPlaylist({ name: made.name, description: `Made by Shelf: ${made.understood.join(", ")}.`, trackIds: made.trackIds });
      toast(`Made “${made.name}” with ${plural(made.trackIds.length, "song")}`);
      location.hash = `#/playlist/${p.id}`;
      break;
    }
    case "pl-smart-new": {
      const made = await editRules({ title: "New smart playlist", askName: true, confirm: "Make it" });
      if (!made) break;
      const p = await api.createPlaylist({ name: made.name, rules: made.rules });
      toast(`Made “${p.name}”: ${plural(p.trackCount, "song")} fit now`);
      location.hash = `#/playlist/${p.id}`;
      break;
    }
    case "pl-rules": {
      const id = parseRoute().id;
      const p = await api.playlist(id);
      const edited = await editRules({ title: "Edit rules", rules: p.smart });
      if (!edited) break;
      await api.editPlaylist(id, { rules: edited.rules });
      invalidate(`playlists/${id}`);
      await redrawPlaylist();
      break;
    }
    case "pl-edit": await editPlaylist(parseRoute().id); break;
    case "pl-findmore": {
      const sec = view.querySelector(".pl-find");
      if (!sec) break;
      sec.hidden = !sec.hidden;
      el.setAttribute("aria-expanded", String(!sec.hidden));
      if (!sec.hidden) sec.querySelector("input")?.focus();
      break;
    }
    case "pl-refresh": await refreshRecommendations(view, parseRoute().id); break;
    case "pl-menu": playlistMenu(parseRoute().id, el); break;
    case "pl-follow": {
      const id = parseRoute().id;
      const on = el.getAttribute("aria-pressed") !== "true";
      await (on ? api.followPlaylist(id) : api.unfollowPlaylist(id));
      toast(on ? "Added to your library" : "Removed from your library");
      await redrawPlaylist();
      break;
    }
    case "pl-add": {
      const id = parseRoute().id;
      // From the playlist's suggestions: taking it back out later teaches them.
      const r = await api.addToPlaylist(id, [Number(el.dataset.track)], { suggested: el.dataset.suggested === "1" });
      toast(`Added to ${r.name}`);
      await redrawPlaylist();
      break;
    }
    case "clear-queue": player.clearUpNext(); break;
    case "keep-smart": local.keepSuggestion(Number(el.dataset.queueIndex)); break;
    case "pl-addpanel":
      if (!(await panel?.openAdd(parseRoute().id))) {
        // Narrow screens: the song search on the page itself.
        const sec = view.querySelector(".pl-find");
        if (sec) { sec.hidden = false; sec.scrollIntoView({ block: "start" }); sec.querySelector("input")?.focus({ preventScroll: true }); }
      }
      break;
    case "pl-mix": {
      const id = parseRoute().id;
      const on = el.getAttribute("aria-pressed") !== "true";
      if (on) { local.engine.ensure(); local.engine.resume(); } // Mix needs the sound engine; this tap allows it
      await api.editPlaylist(id, { mix: on });
      if (local.context?.href === `#/playlist/${id}`) { local.context = { ...local.context, mix: on }; local._plan = null; }
      toast(on ? "Mix is on: songs in this playlist blend into each other" : "Mix is off");
      await redrawPlaylist();
      break;
    }
    case "pl-transition": transitionMenu(Number(el.dataset.index)); break;
    case "eq-reset":
      settings.set({ eqGains: [0, 0, 0, 0, 0, 0], eqPreset: "Flat" });
      break;
    case "clear-history":
      if (el.dataset.confirm !== "1") {
        el.dataset.confirm = "1";
        el.textContent = "Tap again to clear";
        setTimeout(() => { if (el.isConnected) { el.dataset.confirm = ""; el.textContent = "Clear history"; } }, 4000);
        break;
      }
      await api.clearHistory();
      el.dataset.confirm = "";
      el.textContent = "Cleared";
      el.disabled = true;
      toast("Listening history cleared");
      break;
    case "clear-storage": {
      const r = await api.clearStorage();
      toast(`Freed ${Math.round(r.freedBytes / 1e6)} MB`);
      await render();
      break;
    }
    case "folder-add":
    case "folder-change": {
      const replace = action === "folder-change" ? el.dataset.path : null;
      const path = await pickFolder({ title: replace ? "Change folder" : "Add a music folder", start: replace });
      if (!path) break;
      const r = await api.addFolder(path, replace);
      toast(replace
        ? `Changed to ${path}${r.kept ? `. ${plural(r.kept, "song")} found there kept ${r.kept === 1 ? "its" : "their"} likes and playlists.` : ""}`
        : `Added ${path}. Shelf is looking for music in it now.`, 5000);
      afterFolderChange();
      break;
    }
    case "watch-set": {
      const path = await pickFolder({ title: "Choose a watch folder" });
      if (!path) break;
      await api.setWatchFolder(path);
      toast(`Watching ${path}: music dropped in is filed within a minute`, 5000);
      afterFolderChange();
      break;
    }
    case "backup-folder": {
      const path = await pickFolder({ title: "Choose a folder for backups" });
      if (!path) break;
      await api.setBackupFolder(path);
      toast(`Backups go to ${path} from now on`, 4000);
      if (parseRoute().name === "admin") render();
      break;
    }
    case "watch-off":
      await api.setWatchFolder("");
      toast("Watch folder off");
      afterFolderChange();
      break;
    case "folder-remove": {
      const path = el.dataset.path;
      const ok = await dialog({
        title: "Remove this folder?",
        text: `Songs in ${path} leave your library, along with their likes and places in playlists. The files themselves aren’t touched.`,
        confirm: "Remove", danger: true,
      });
      if (!ok) break;
      await api.removeFolder(path);
      toast(`Removed ${path} from your library`);
      afterFolderChange();
      break;
    }
    case "rescan":
      await api.rescan();
      setTimeout(() => library?.refresh(), 4000);
      toast("Rescanning your library");
      el.disabled = true;
      setTimeout(() => { if (parseRoute().name === "admin") render(); }, 1500);
      break;
    case "logout":
      await api.logout().catch(() => {});
      showLogin();
      break;
    case "change-server":
      if (android) { android.changeServer(); break; }
      await dialog({
        title: "Change server",
        text: "Open another Shelf server. You’ll sign in there with your account on that server.",
        fields: [{ name: "server", label: "Server address", value: currentServer().replace(/^https?:\/\//, ""), autocomplete: "url",
          hint: "Like 192.168.1.20:4533, or the address you open it at in a browser." }],
        confirm: "Connect",
        submit: async (v) => {
          if (!(await switchServer(v.server))) throw new Error("That’s the server you’re on now.");
        },
      });
      break;
    case "act-play": {
      const a = ctx.activity?.find((x) => (x.now?.track ?? x.last?.track)?.id === Number(el.dataset.track));
      const t = a?.now?.track ?? a?.last?.track;
      if (t) player.playList([t], 0, { context: { label: `${a.user.username}’s listening`, href: "#/people" } });
      break;
    }
    case "lb-connect": {
      const me = await dialog({
        title: "Connect ListenBrainz",
        text: "Copy your user token from listenbrainz.org/settings (sign in there first) and paste it here.",
        fields: [{ name: "token", label: "User token", autocomplete: "off" }],
        confirm: "Connect",
        submit: (v) => api.editMe({ listenbrainzToken: v.token }),
      });
      if (!me) break;
      session.user = { ...session.user, ...me };
      toast(`Connected to ListenBrainz as ${me.listenbrainz}`);
      render();
      break;
    }
    case "lfm-connect": {
      const tab = window.open("", "_blank"); // now, while it's a click: browsers block tabs opened later
      try {
        const { url } = await api.lastfmStart();
        if (tab) tab.location = url; else window.open(url, "_blank");
      } catch (e) { tab?.close(); toast(e.message); break; }
      const me = await dialog({
        title: "Connect Last.fm",
        text: "Last.fm opened in a new tab. Choose “Yes, allow access” there, then come back and choose Done.",
        confirm: "Done",
        submit: () => api.lastfmFinish(),
      });
      if (!me) break;
      session.user = { ...session.user, lastfm: me.lastfm };
      toast(`Scrobbling to Last.fm as ${me.lastfm}`);
      render();
      break;
    }
    case "lfm-disconnect":
      await api.lastfmDisconnect();
      session.user = { ...session.user, lastfm: null };
      toast("Last.fm disconnected");
      render();
      break;
    case "subsonic-on":
    case "subsonic-show": {
      const d = action === "subsonic-on" ? await api.subsonicOn() : await api.subsonic();
      if (action === "subsonic-on") { session.user = { ...session.user, subsonic: true }; render(); }
      await dialog({
        title: "Sign in to other music apps",
        text: "In the app, add a Subsonic (or Navidrome) server with these details. The app password only works in those apps; your own password stays yours.",
        fields: [
          { name: "server", label: "Server address", value: currentServer() },
          { name: "username", label: "Username", value: d.username },
          { name: "password", label: "App password", value: d.password ?? "" },
        ],
        confirm: "Done",
      });
      break;
    }
    case "whats-new":
      await showWhatsNew({ admin: !!session.user?.admin });
      break;
    case "share-links":
      await manageLinks();
      break;
    case "subsonic-off": {
      const ok = await dialog({
        title: "Turn off other music apps?",
        text: "Apps signed in with your app password stop working. Setting up again makes a new password.",
        confirm: "Turn off", danger: true,
      });
      if (!ok) break;
      await api.subsonicOff();
      session.user = { ...session.user, subsonic: false };
      toast("Other music apps can’t sign in now");
      render();
      break;
    }
    case "lb-disconnect":
      session.user = { ...session.user, ...(await api.editMe({ listenbrainzToken: "" })) };
      toast("ListenBrainz disconnected");
      render();
      break;
    case "share-activity": {
      const on = el.getAttribute("aria-checked") !== "true";
      session.user = { ...session.user, ...(await api.editMe({ shareActivity: on })) };
      el.setAttribute("aria-checked", String(on));
      toast(on ? "People on this server can see what you play" : "What you play is private now");
      break;
    }
    case "releases-check":
      await api.checkReleases();
      toast("Checking MusicBrainz for your artists’ releases. This takes a minute or two.");
      setTimeout(() => { if (parseRoute().name === "releases") render(); }, 4000);
      break;
    case "me-menu": meMenu(el); break;
    case "play-mix": {
      const m = await api.mix(el.dataset.key);
      player.playList(m.tracks, 0, { context: { label: m.name, href: `#/mix/${m.key}` } });
      break;
    }
    case "mix-save": {
      const m = ctx.mix;
      if (!m) break;
      const p = await api.createPlaylist({ name: m.name, description: m.description, trackIds: m.tracks.map((t) => t.id) });
      toast(`Saved as the playlist “${p.name}”`);
      location.hash = `#/playlist/${p.id}`;
      break;
    }
    case "artist-radio":
      location.hash = `#/radio/artist/${encodeURIComponent(el.dataset.artist)}`;
      break;
    case "download": {
      const { kind, id } = el.dataset;
      const key = el.dataset.dl;
      if (!offline.isSaved(key)) {
        if (isOffline) { toast("Connect to the internet to download"); break; }
        const data = kind === "album" ? await api.album(Number(id)) : kind === "playlist" ? await api.playlist(Number(id)) : await api.likes();
        await offline.save(kind, id ? Number(id) : null, data);
        toast(kind === "liked" ? "Downloading Favourites" : `Downloading ${kind === "album" ? data.title : data.name}`);
      } else {
        const c = offline.list().find((x) => x.key === key);
        const ok = await dialog({
          title: "Remove from downloads?",
          text: `You won’t be able to play ${c?.title ?? "this"} with no connection. You can download it again any time.`,
          confirm: "Remove", danger: true,
        });
        if (!ok) break;
        await offline.remove(key);
        toast("Removed from downloads");
      }
      break;
    }
    case "downloads-clear": {
      const ok = await dialog({
        title: "Remove all downloads?",
        text: "Everything downloaded to this device is deleted. Your library on the server isn’t touched.",
        confirm: "Remove all", danger: true,
      });
      if (!ok) break;
      await offline.removeAll();
      toast("Removed all downloads");
      render();
      break;
    }
    case "change-password": {
      const ok = await dialog({
        title: "Change your password",
        text: "You’ll stay signed in here. Your other devices will need the new password.",
        fields: [
          { name: "current", label: "Current password", type: "password", autocomplete: "current-password" },
          { name: "next", label: "New password", type: "password", autocomplete: "new-password", hint: "At least 6 characters." },
          { name: "again", label: "New password again", type: "password", autocomplete: "new-password" },
        ],
        confirm: "Change password",
        submit: async (v) => {
          if (v.next !== v.again) throw new Error("The new passwords don’t match.");
          await api.changePassword(v.current, v.next);
        },
      });
      if (ok) toast("Password changed");
      break;
    }
  }
}

// ---------- playlists ----------

/** Re-render the playlist page in place, keeping the scroll position and the song search. */
async function redrawPlaylist() {
  const r = parseRoute();
  if (r.name !== "playlist") return;
  const top = view.scrollTop;
  const find = view.querySelector("#pl-find")?.value ?? "";
  const hadFocus = document.activeElement?.id === "pl-find";
  unmountPage?.();
  await playlistView(view, r.id, { find });
  unmountPage = albumStickyHead();
  view.scrollTop = top;
  markPlayingRow();
  if (hadFocus) view.querySelector("#pl-find")?.focus({ preventScroll: true });
}

window.addEventListener("playlists-changed", () => {
  if (parseRoute().name === "playlists") playlistsView(view).catch(() => {});
});

/** After the music folders change: show the new list now, and the library once the scan is done. */
function afterFolderChange() {
  if (parseRoute().name === "admin") render();
  let tries = 0;
  const poll = setInterval(async () => {
    const lib = await api.library().catch(() => null);
    if (++tries > 120 || (lib && !lib.scan.running)) {
      clearInterval(poll);
      library?.refresh();
      likes.load(true);
      if (parseRoute().name === "admin") render();
    }
  }, 2000);
}

/** Pick a folder on the server: the browser can't see the server's disks, so Shelf lists them. */
function pickFolder({ title, start = null }) {
  return new Promise((resolve) => {
    const d = document.createElement("dialog");
    d.className = "dialog picker";
    d.innerHTML = `
      <form method="dialog">
        <h2>${esc(title)}</h2>
        <p>Choose the folder on the server where the music is. Folders inside it are included.</p>
        <div class="picker-starts" id="pk-starts"></div>
        <div class="picker-bar">
          <button class="icon-btn" type="button" id="pk-up" aria-label="Up one folder" title="Up one folder"><svg><use href="#i-back"/></svg></button>
          <input class="picker-path" id="pk-path" aria-label="Folder path" autocomplete="off" spellcheck="false">
        </div>
        <div class="picker-list" id="pk-list" role="list"></div>
        <p class="picker-note" id="pk-note"></p>
        <div class="dialog-actions">
          <button class="btn" type="button" value="cancel">Cancel</button>
          <button class="btn btn-primary" type="submit" value="ok" id="pk-ok">Choose this folder</button>
        </div>
      </form>`;
    document.body.append(d);
    const $$ = (id) => d.querySelector(`#${id}`);
    let here = null;
    const go = async (path) => {
      const r = await api.browseFolders(path).catch((e) => ({ error: e.message, dirs: [], starts: [] }));
      if (r.path) here = r;
      $$("pk-path").value = r.path ?? path ?? "";
      $$("pk-up").disabled = !r.parent;
      $$("pk-starts").innerHTML = r.starts.map((x) => `<button class="chip" type="button" data-go="${esc(x.path)}">${esc(x.name)}</button>`).join("");
      $$("pk-list").innerHTML = r.dirs.map((x) => `
        <button class="picker-dir" type="button" role="listitem" data-go="${esc(x.path)}"><svg><use href="#i-folder"/></svg><span>${esc(x.name)}</span></button>`).join("")
        || `<p class="picker-note">${r.error ? "" : "No folders inside this one."}</p>`;
      const note = $$("pk-note");
      note.textContent = r.error ?? (r.inLibrary ? "This folder is already in your library." : "");
      note.classList.toggle("bad", !!r.error);
      $$("pk-list").scrollTop = 0;
    };
    d.addEventListener("click", (e) => {
      const b = e.target.closest("[data-go]");
      if (b) { e.preventDefault(); go(b.dataset.go); }
    });
    $$("pk-up").addEventListener("click", () => here?.parent && go(here.parent));
    $$("pk-path").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); go($$("pk-path").value.trim()); } });
    d.querySelector('[value="cancel"]').addEventListener("click", () => d.close("cancel"));
    d.querySelector("form").addEventListener("submit", (e) => { e.preventDefault(); d.close("ok"); });
    d.addEventListener("close", () => {
      const typed = $$("pk-path").value.trim();
      d.remove();
      resolve(d.returnValue === "ok" ? typed || here?.path || null : null);
    });
    d.showModal();
    go(start);
  });
}

/** A small dialog. `fields`: [{ name, label, value, multiline }]. Resolves with the values, or null. */
/**
 * A small modal form. fields: [{ name, label, value?, multiline?, type?, hint?, autocomplete? }]
 * (type "checkbox" makes a switch-like checkbox). With `submit`, the dialog stays open until it
 * resolves; if it throws, its message shows in the dialog.
 */
function dialog({ title, text, fields = [], confirm, danger = false, submit = null }) {
  return new Promise((resolve) => {
    const d = document.createElement("dialog");
    d.className = "dialog";
    const field = (f) => {
      if (f.type === "checkbox") {
        return `<label class="check-field"><input type="checkbox" name="${f.name}" ${f.value ? "checked" : ""}><span>${esc(f.label)}${f.hint ? `<small>${esc(f.hint)}</small>` : ""}</span></label>`;
      }
      const input = f.multiline
        ? `<textarea name="${f.name}" rows="3" maxlength="2000">${esc(f.value ?? "")}</textarea>`
        : `<input name="${f.name}" type="${f.type ?? "text"}" value="${esc(f.value ?? "")}" maxlength="200" autocomplete="${f.autocomplete ?? "off"}" autocapitalize="off" spellcheck="false">`;
      return `<label class="field"><span>${esc(f.label)}</span>${input}${f.hint ? `<small class="field-hint">${esc(f.hint)}</small>` : ""}</label>`;
    };
    d.innerHTML = `
      <form method="dialog">
        <h2>${esc(title)}</h2>
        ${text ? `<p>${esc(text)}</p>` : ""}
        ${fields.map(field).join("")}
        <p class="dialog-error" role="alert"></p>
        <div class="dialog-actions">
          <button class="btn" type="button" value="cancel">Cancel</button>
          <button class="btn ${danger ? "btn-danger" : "btn-primary"}" type="submit" value="ok">${esc(confirm)}</button>
        </div>
      </form>`;
    document.body.append(d);
    const form = d.querySelector("form");
    const values = () => {
      const v = Object.fromEntries(new FormData(form));
      for (const f of fields) if (f.type === "checkbox") v[f.name] = !!form.elements[f.name].checked;
      return v;
    };
    let result = null;
    d.querySelector('[value="cancel"]').addEventListener("click", () => d.close("cancel"));
    d.addEventListener("close", () => { d.remove(); resolve(result); });
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const v = values();
      if (submit) {
        const btn = form.querySelector('[type="submit"]');
        btn.disabled = true;
        try {
          result = (await submit(v)) ?? v;
        } catch (err) {
          form.querySelector(".dialog-error").textContent = err.message;
          btn.disabled = false;
          return;
        }
      } else {
        result = v;
      }
      d.close("ok");
    });
    d.showModal();
    d.querySelector("input:not([type=checkbox]), textarea")?.select();
  });
}

async function editPlaylist(id) {
  const p = await api.playlist(id);
  const v = await dialog({
    title: "Edit details",
    fields: [{ name: "name", label: "Name", value: p.name }, { name: "description", label: "Description", value: p.description, multiline: true }],
    confirm: "Save",
  });
  if (!v) return;
  await api.editPlaylist(id, { name: v.name, description: v.description });
  await redrawPlaylist();
}

async function deletePlaylist(id) {
  const p = await api.playlist(id);
  const ok = await dialog({
    title: `Delete “${p.name}”?`,
    text: "This removes the playlist from Shelf on every device. The songs stay in your library.",
    confirm: "Delete", danger: true,
  });
  if (!ok) return;
  await api.deletePlaylist(id);
  toast(`Deleted “${p.name}”`);
  if (parseRoute().name === "playlist" && parseRoute().id === id) location.hash = "#/playlists";
}

function playlistMenu(id, at) {
  const shared = ctx.context?.shared ?? 0;
  const share = (level, label, sub, icon) => ({
    label, sub, icon: level === shared ? "i-check" : icon, current: level === shared,
    run: () => api.editPlaylist(id, { shared: level }).then(() => {
      toast(level === 0 ? "Only you can see this playlist now" : level === 1 ? "Everyone on this server can play and follow it now" : "Everyone on this server can add songs to it now");
      return redrawPlaylist();
    }).catch((e) => toast(e.message)),
  });
  openMenu({
    at,
    items: [
      share(0, "Private", "Only you", "i-lock"),
      share(1, "Public", "Everyone here can play and follow it", "i-globe"),
      share(2, "Collaborative", "Everyone here can add songs too", "i-people"),
      "sep",
      { label: "Edit details", icon: "i-edit", run: () => editPlaylist(id).catch((e) => toast(e.message)) },
      { label: "Add to queue", icon: "i-plus", run: () => { if (ctx.tracks.length) player.addToQueue(ctx.tracks); } },
      ...(session.user?.shareLinks ? [{ label: "Share link", icon: "i-link", run: () => shareLink("playlist", id, ctx.context?.playlistId === id ? ctx.context.label : "this playlist") }] : []),
      "sep",
      { label: "Delete playlist", icon: "i-trash", run: () => deletePlaylist(id).catch((e) => toast(e.message)) },
    ],
  });
}

/** Mix: edit how a song hands over to the next one (in the side panel, or full screen on phones). */
function transitionMenu(i) {
  const t = ctx.tracks[i], nxt = ctx.tracks[i + 1];
  if (!t || !nxt) return;
  const pid = parseRoute().id;
  const opts = {
    player, tracks: ctx.tracks, index: i, context: ctx.context,
    onSave: async (setting) => {
      try {
        await api.setTransition(pid, t.entryId, setting);
        // The queue may be playing this playlist: let it pick the change up.
        for (const q of local.queue) if (q.entryId === t.entryId) q.transition = setting;
        local._plan = null;
        toast("Transition saved");
        await redrawPlaylist();
      } catch (e) { toast(e.message); }
    },
  };
  if (panel?.openTransition(opts)) return;
  const d = document.createElement("dialog");
  d.className = "tre-sheet";
  document.body.append(d);
  const handle = mountTransitionEditor(d, { ...opts, onClose: () => d.close() });
  d.addEventListener("close", () => { handle.close(); d.remove(); });
  d.showModal();
}

window.addEventListener("likes-changed", () => {
  library?.refresh();
  if (offline.isSaved("liked")) syncSoon("liked");
  const r = parseRoute().name;
  if (r === "liked") { const top = view.scrollTop; likedView(view).then(() => { view.scrollTop = top; markPlayingRow(); }).catch(() => {}); }
  if (r === "playlists") playlistsView(view).catch(() => {});
});

/** "Add to playlist": pick one (or start a new one). `getIds` may be async (whole albums). */
async function addToPlaylistMenu(getIds, at) {
  const lists = await api.playlists().catch(() => []);
  const add = async (p) => {
    const ids = await getIds();
    if (!p) {
      const made = await api.createPlaylist({ trackIds: ids });
      toast(`Added to ${made.name}`);
    } else {
      await api.addToPlaylist(p.id, ids);
      toast(`Added to ${p.name}`);
    }
    if (parseRoute().name === "playlist" && (!p || parseRoute().id === p.id)) await redrawPlaylist();
  };
  openMenu({
    at,
    heading: "Add to playlist",
    items: [
      { label: "New playlist", icon: "i-plus", run: () => add(null).catch((e) => toast(e.message)) },
      ...(lists.length ? ["sep"] : []),
      ...lists.map((p) => ({ label: p.name, sub: plural(p.trackCount, "song"), icon: "i-playlist", run: () => add(p).catch((e) => toast(e.message)) })),
    ],
  });
}

// ---------- quick-action menus ----------

const albumContext = (a) => ({ label: a.title, href: `#/album/${a.id}` });

/** Everyone credited on a song: its own artists, then its album's (each once). */
function trackArtists(t) {
  const seen = new Set();
  return [...(t.artists ?? [t.artist]), ...(t.albumArtists ?? (t.albumArtist ? [t.albumArtist] : []))]
    .filter((n) => n && !seen.has(n.toLowerCase()) && seen.add(n.toLowerCase()));
}

function albumMenu(card, at) {
  const id = Number(card.dataset.album);
  const artist = card.dataset.artist;
  let artists;
  try { artists = JSON.parse(card.dataset.artists); } catch { artists = [artist]; }
  const title = card.dataset.title ?? card.querySelector(".card-title")?.textContent ?? "";
  const withAlbum = (fn) => () => api.album(id).then(fn).catch((e) => toast(e.message));
  openMenu({
    at,
    header: { art: card.querySelector(".case")?.outerHTML.replace('class="case ', 'class="case case-sm '), title, sub: artist },
    items: [
      { label: "Play", icon: "i-play", run: withAlbum((a) => player.playList(a.tracks, 0, { context: albumContext(a) })) },
      { label: "Shuffle", icon: "i-shuffle", run: withAlbum((a) => player.playList(a.tracks, 0, { shuffle: true, context: albumContext(a) })) },
      { label: "Play next", icon: "i-next-up", run: withAlbum((a) => player.playNext(a.tracks)) },
      { label: "Add to queue", icon: "i-plus", run: withAlbum((a) => player.addToQueue(a.tracks)) },
      { label: "Add to playlist", icon: "i-playlist", run: () => addToPlaylistMenu(() => api.album(id).then((a) => a.tracks.map((t) => t.id)), at) },
      ...(session.user?.shareLinks ? [{ label: "Share link", icon: "i-link", run: () => shareLink("album", id, title) }] : []),
      "sep",
      { label: "Go to album", icon: "i-album-go", run: () => { location.hash = `#/album/${id}`; } },
      ...artistItems(artists),
    ],
  });
}

function trackMenu(i, at) {
  const t = ctx.tracks[i];
  if (!t) return;
  const route = parseRoute();
  const onAlbumPage = route.name === "album" && route.id === t.albumId;
  openMenu({
    at,
    header: { art: caseHtml(t, { size: 160, cls: "case-sm" }), title: t.title, sub: `${t.artist}, ${t.album}` },
    items: [
      { label: "Play", icon: "i-play", run: () => player.playList(ctx.tracks, i, { context: ctx.context }) },
      { label: "Play next", icon: "i-next-up", run: () => player.playNext([t]) },
      { label: "Add to queue", icon: "i-plus", run: () => player.addToQueue([t]) },
      { label: "Add to playlist", icon: "i-playlist", run: () => addToPlaylistMenu(() => [t.id], at) },
      { label: likes.has(t.id) ? "Remove from Favourites" : "Add to Favourites", icon: "i-heart", run: () => likes.toggle(t.id) },
      { label: "Go to song radio", icon: "i-radio", run: () => { location.hash = `#/radio/track/${t.id}`; } },
      ...(session.user?.shareLinks ? [{ label: "Share link", icon: "i-link", run: () => shareLink("track", t.id, t.title) }] : []),
      ...(t.entryId && route.name === "playlist" && ctx.context?.canEdit ? [
        "sep",
        ...(i > 0 ? [{ label: "Move up", icon: "i-back", run: () => movePlaylistEntry(i, i - 1) }] : []),
        ...(i < ctx.tracks.length - 1 ? [{ label: "Move down", icon: "i-forward", run: () => movePlaylistEntry(i, i + 1) }] : []),
        { label: "Remove from this playlist", icon: "i-trash", run: () => removeFromPlaylist(route.id, t) },
      ] : []),
      "sep",
      ...(onAlbumPage ? [] : [{ label: "Go to album", icon: "i-album-go", run: () => { location.hash = `#/album/${t.albumId}`; } }]),
      ...artistItems(trackArtists(t)),
    ],
  });
}

async function removeFromPlaylist(pid, t) {
  try {
    await api.removeFromPlaylist(pid, t.entryId);
    toast(`Removed “${t.title}”`);
    await redrawPlaylist();
  } catch (e) { toast(e.message); }
}

async function movePlaylistEntry(from, to) {
  const ids = ctx.tracks.map((t) => t.entryId);
  const [moved] = ids.splice(from, 1);
  ids.splice(to, 0, moved);
  const before = rowPositions();
  try {
    await api.reorderPlaylist(parseRoute().id, ids);
  } catch (e) { toast(e.message); }
  await redrawPlaylist();
  glideRows(before, moved);
}

// ---------- drop and reorder animations ----------

const motionOK = () => !reducedMotion.matches;

/** The song's (or album's) cover flies from the drop point into the playlist's cover. */
function flyInto(x, y, cover, target) {
  if (!motionOK()) return Promise.resolve();
  const dest = (target.querySelector(".pl-cover") ?? target).getBoundingClientRect();
  const card = document.createElement("div");
  card.className = "fly-card";
  card.innerHTML = cover ? `<img src="${esc(cover)}" alt="">` : `<svg><use href="#i-note"/></svg>`;
  card.style.left = `${x - 28}px`;
  card.style.top = `${y - 28}px`;
  document.body.append(card);
  const dx = dest.left + dest.width / 2 - x;
  const dy = dest.top + dest.height / 2 - y;
  const lift = Math.min(90, Math.hypot(dx, dy) * 0.25);
  const anim = card.animate([
    { transform: "translate(0, 0) scale(1) rotate(0deg)", opacity: 1 },
    { transform: `translate(${dx * 0.45}px, ${dy * 0.45 - lift}px) scale(0.85) rotate(-6deg)`, opacity: 1, offset: 0.45 },
    { transform: `translate(${dx}px, ${dy}px) scale(${Math.max(0.2, dest.width / 56 * 0.6)}) rotate(0deg)`, opacity: 0.15 },
  ], { duration: 560, easing: "cubic-bezier(.45, 0, .25, 1)" });
  return anim.finished.catch(() => {}).finally(() => card.remove());
}

/** The playlist that just got songs gives a little bump. */
function bumpPlaylist(id) {
  if (!motionOK()) return;
  document.querySelectorAll(`.lib-item[data-playlist="${id}"], .pl-card[data-playlist="${id}"]`).forEach((el) => {
    el.classList.remove("pl-bump");
    void el.offsetWidth; // restart the animation if it's already running
    el.classList.add("pl-bump");
    el.addEventListener("animationend", () => el.classList.remove("pl-bump"), { once: true });
  });
}

function rowPositions() {
  const m = new Map();
  view.querySelectorAll(".pl-tracks .pl-row[data-entry]").forEach((r) => m.set(r.dataset.entry, r.getBoundingClientRect().top));
  return m;
}

/** After a reorder, each row slides from where it was to where it is (FLIP). */
function glideRows(before, movedEntry) {
  const rows = view.querySelectorAll(".pl-tracks .pl-row[data-entry]");
  const moved = view.querySelector(`.pl-tracks .pl-row[data-entry="${movedEntry}"]`);
  if (moved) {
    moved.classList.add("pl-moved");
    setTimeout(() => moved.classList.remove("pl-moved"), 1300);
  }
  if (!motionOK()) return;
  rows.forEach((r) => {
    const was = before.get(r.dataset.entry);
    if (was == null) return;
    const dy = was - r.getBoundingClientRect().top;
    if (Math.abs(dy) < 1) return;
    r.animate([{ transform: `translateY(${dy}px)` }, { transform: "translateY(0)" }],
      { duration: r === moved ? 420 : 320, easing: "cubic-bezier(.2, .8, .2, 1)" });
  });
}

function queueMenu(qi, at) {
  const t = player.queue[qi];
  if (!t) return;
  const actions = [
    ...(qi === player.index ? [] : [{ label: "Play now", icon: "i-play", run: () => player.jumpTo(qi) }]),
    ...(qi > player.index ? [{ label: "Remove from queue", icon: "i-close", run: () => player.removeAt(qi) }] : []),
    { label: "Add to playlist", icon: "i-playlist", run: () => addToPlaylistMenu(() => [t.id], at) },
    { label: "Go to song radio", icon: "i-radio", run: () => { location.hash = `#/radio/track/${t.id}`; } },
  ];
  openMenu({
    at,
    header: { art: caseHtml(t, { size: 160, cls: "case-sm" }), title: t.title, sub: `${t.artist}, ${t.album}` },
    items: [
      ...actions,
      ...(actions.length ? ["sep"] : []),
      { label: "Go to album", icon: "i-album-go", run: () => { location.hash = `#/album/${t.albumId}`; } },
      ...artistItems(trackArtists(t)),
    ],
  });
}

function menuFor(target, at) {
  const card = target.closest(".album-card[data-album]");
  if (card) { albumMenu(card, at); return true; }
  const q = target.closest(".track-row[data-queue-index]");
  if (q) { queueMenu(Number(q.dataset.queueIndex), at); return true; }
  const row = target.closest(".track-row[data-index]");
  if (row) { trackMenu(rowIndex(row), at); return true; }
  return false;
}

view.addEventListener("contextmenu", (e) => {
  if (menuOpen()) { e.preventDefault(); return; }
  const at = e.clientX || e.clientY ? { x: e.clientX, y: e.clientY } : e.target;
  if (menuFor(e.target, at)) e.preventDefault();
});

// Long-press on touch screens (iOS doesn't send contextmenu for it).
let press = null;
view.addEventListener("pointerdown", (e) => {
  if (e.pointerType !== "touch" || !e.target.closest(".album-card, .track-row")) return;
  const start = { x: e.clientX, y: e.clientY };
  press = {
    start,
    timer: setTimeout(() => {
      press = null;
      if (menuOpen()) return;
      if (menuFor(e.target, start)) {
        suppressClick = true;
        navigator.vibrate?.(8);
      }
    }, 480),
  };
});
const cancelPress = (e) => {
  if (!press) return;
  if (e.type === "pointermove" && Math.hypot(e.clientX - press.start.x, e.clientY - press.start.y) < 10) return;
  clearTimeout(press.timer);
  press = null;
};
for (const t of ["pointermove", "pointerup", "pointercancel"]) view.addEventListener(t, cancelPress);
document.addEventListener("pointerup", () => { if (suppressClick) setTimeout(() => { suppressClick = false; }, 400); });

// ---------- player bar + now playing ----------

const STREAM_LABEL = { low: "AAC 96", normal: "AAC 128", high: "AAC 192", veryhigh: "AAC 320" };

function setPlayIcon(btn, playing) {
  btn.querySelector("use").setAttribute("href", playing ? "#i-pause" : "#i-play");
  btn.setAttribute("aria-label", playing ? "Pause" : "Play");
}

function setRepeat(btn) {
  btn.dataset.mode = player.repeat;
  btn.querySelector("use").setAttribute("href", player.repeat === "one" ? "#i-repeat-one" : "#i-repeat");
  btn.setAttribute("aria-label", { off: "Repeat: off", all: "Repeat: all", one: "Repeat: this song" }[player.repeat]);
}

function setBadge(el, t) {
  const streamed = STREAM_LABEL[player.currentQuality];
  const q = streamed ? null : quality(t);
  el.textContent = streamed ?? q?.short ?? "";
  el.title = streamed ? "Streaming a smaller copy" : q?.detail ?? "";
  el.classList.toggle("lossless", !!q?.lossless);
}

let shownTrackId = null;
function syncTrack() {
  const t = player.current;
  $("player").dataset.empty = t ? "false" : "true";
  if (!t) return;
  $("player-title").textContent = t.title;
  $("player-artist").textContent = t.artist;
  if (shownTrackId !== t.id) {
    shownTrackId = t.id;
    $("player-cover").outerHTML = caseHtml(t, { size: 160, cls: "case-sm", lazy: false }).replace('class="case', 'id="player-cover" class="case');
    $("np-cover").outerHTML = caseHtml(t, { size: 1200, cls: "case-lg", lazy: false, sizes: "(max-width: 760px) 70vw, 460px" }).replace('class="case', 'id="np-cover" class="case');
    const art = t.cover ? `url("${coverUrl(t.albumId, t.cover, 640)}")` : "none";
    $("np-disc-face").style.backgroundImage = art; // the CD: printed all over
    $("np-disc-face").style.setProperty("--art", art); // the record: on its centre label
    $("np-backdrop").style.backgroundImage = t.cover ? `url("${coverUrl(t.albumId, t.cover, 160)}")` : "none";
  }
  for (const id of ["player-like", "np-like"]) { $(id).dataset.like = t.id; $(id).hidden = false; }
  refreshHearts($("player"));
  refreshHearts($("nowplaying"));
  $("np-title").textContent = t.title;
  $("np-artist").innerHTML = artistLinks(t.artist, t.artists);
  const from = player.context ?? { label: t.album, href: `#/album/${t.albumId}` };
  $("np-from").textContent = from.label;
  $("np-from").href = from.href;
  albumColorFor(t);
}

// Track objects don't carry the album color; it comes from the (cached) album.
async function albumColorFor(t) {
  const color = await api.album(t.albumId).then((a) => a.color).catch(() => null);
  if (player.current?.albumId === t.albumId) {
    applyAlbumColor($("player"), color);
    applyAlbumColor($("nowplaying"), color);
  }
}

function syncPlayer() {
  syncTrack();
  const playing = transport.playing;
  const t = player.current;
  setPlayIcon($("btn-play"), playing);
  setPlayIcon($("np-play"), playing);
  $("np-deck").dataset.playing = String(playing);
  for (const id of ["btn-shuffle", "np-shuffle"]) {
    const smart = player.shuffle === "smart";
    const label = smart ? "Smart shuffle: on (select to turn off)" : player.shuffle ? "Shuffle: on (select for smart shuffle)" : "Shuffle";
    $(id).setAttribute("aria-pressed", String(!!player.shuffle));
    $(id).setAttribute("aria-label", label);
    $(id).title = label;
    $(id).querySelector("use").setAttribute("href", smart ? "#i-shuffle-smart" : "#i-shuffle");
  }
  setRepeat($("btn-repeat"));
  setRepeat($("np-repeat"));
  if (t) {
    setBadge($("np-quality"), t);
  }
  const nxt = player.nextTrack;
  $("np-upnext").innerHTML = player.repeat === "one" ? "Repeating this song"
    : nxt ? `Next: <b>${esc(nxt.title)}</b>, ${esc(nxt.artist)}` : "";
  markPlayingRow();
  syncVolume();
  const route = parseRoute().name;
  if (route === "queue") {
    const top = view.scrollTop;
    queueView(view, player);
    view.scrollTop = top;
  } else if (route === "home") {
    const btn = view.querySelector('.hero [data-action="toggle"]');
    if (btn) btn.innerHTML = `<svg><use href="#${playing ? "i-pause" : "i-play"}"/></svg>${playing ? "Pause" : "Resume"}`;
  }
}

function markPlayingRow() {
  const t = player.current;
  // A mix tape's reels turn while that mix plays.
  const from = player.playing ? player.context?.href : null;
  view.querySelectorAll(".mix-tape").forEach((el) => el.classList.toggle("rolling", !!from && el.dataset.href === from));
  view.querySelectorAll(".track-row.playing").forEach((r) => {
    if (r.dataset.queueIndex) return;
    r.classList.remove("playing", "paused");
    const num = r.querySelector(".num");
    if (num?.dataset.n) num.textContent = num.dataset.n;
  });
  if (!t) return;
  view.querySelectorAll(`.track-row[data-track="${t.id}"]:not([data-queue-index])`).forEach((r) => {
    r.classList.add("playing");
    r.classList.toggle("paused", !player.playing);
    const num = r.querySelector(".num");
    if (num) {
      num.dataset.n ??= num.textContent;
      num.innerHTML = `<span class="eq" aria-label="Playing"><i></i><i></i><i></i></span>`;
    }
  });
}

let seeking = false;
function syncTime() {
  const d = transport.duration, c = transport.position;
  const pct = d ? (c / d) * 100 : 0;
  $("time-cur").textContent = fmtTime(c);
  $("time-dur").textContent = fmtTime(d);
  $("np-cur").textContent = fmtTime(c);
  $("np-dur").textContent = `-${fmtTime(Math.max(0, d - c))}`;
  $("mini-fill").style.transform = `scaleX(${pct / 100})`;
  if (!seeking) {
    for (const id of ["seek", "np-seek"]) {
      $(id).value = String(Math.round(pct * 10));
      $(id).style.setProperty("--pct", `${pct}%`);
    }
  }
}

for (const id of ["seek", "np-seek"]) {
  const input = $(id);
  input.addEventListener("input", () => {
    seeking = true;
    input.style.setProperty("--pct", `${input.value / 10}%`);
    $(id === "seek" ? "time-cur" : "np-cur").textContent = fmtTime((input.value / 1000) * transport.duration);
  });
  input.addEventListener("change", () => {
    transport.seek((input.value / 1000) * transport.duration);
    seeking = false;
  });
}

let volumeHeld = false;
function syncVolume() {
  if (volumeHeld) return;
  syncMute();
  $("volume").value = String(player.volume);
  $("volume").style.setProperty("--pct", `${player.volume * 100}%`);
}
syncVolume();
$("volume").addEventListener("pointerdown", () => { volumeHeld = true; });
$("volume").addEventListener("change", () => { volumeHeld = false; });
let unmuted = Number(store.get("unmutedVolume", 1)) || 1;
function syncMute() {
  const muted = player.volume === 0;
  $("btn-mute").querySelector("use").setAttribute("href", muted ? "#i-mute" : "#i-volume");
  $("btn-mute").setAttribute("aria-label", muted ? "Unmute" : "Mute");
  $("btn-mute").title = muted ? "Unmute" : "Mute";
}
$("btn-mute").addEventListener("click", () => {
  if (player.volume > 0) { unmuted = player.volume; store.set("unmutedVolume", unmuted); player.setVolume(0); }
  else player.setVolume(unmuted || 1);
  volumeHeld = false;
  syncVolume();
});
$("volume").addEventListener("input", (e) => {
  player.setVolume(Number(e.target.value));
  syncMute();
  e.target.style.setProperty("--pct", `${e.target.value * 100}%`);
});

const transport = {
  toggle: () => (video.active ? video.toggle() : player.toggle()),
  next: () => { if (video.active) video.stop(false); player.next(); },
  prev: () => { if (video.active) { video.seek(0); return; } player.prev(); },
  seek: (sec) => (video.active ? video.seek(sec) : player.seek(sec)),
  get position() { return video.active ? video.time : player.position; },
  get duration() { return video.active ? video.duration || player.duration : player.duration; },
  get playing() { return video.active ? video.playing : player.playing; },
};

for (const [a, b, fn] of [
  ["btn-play", "np-play", () => transport.toggle()],
  ["btn-next", "np-next", () => transport.next()],
  ["btn-prev", "np-prev", () => transport.prev()],
  ["btn-shuffle", "np-shuffle", () => player.toggleShuffle()],
  ["btn-repeat", "np-repeat", () => player.cycleRepeat()],
]) {
  $(a).addEventListener("click", fn);
  $(b).addEventListener("click", fn);
}

player.addEventListener("track", () => {
  syncTrack();
  if (parseRoute().name === "home" && !firstRender) render();
});
player.addEventListener("state", syncPlayer);
player.addEventListener("time", syncTime);

// Now playing opens with the mini-player cover growing into the big one.
function morphNowPlaying(open) {
  const np = $("nowplaying");
  const swap = () => {
    np.hidden = !open;
    document.body.classList.toggle("np-open", open);
  };
  if (!canMorph || reducedMotion.matches) {
    swap();
    return;
  }
  const from = open ? $("player-cover") : $("np-cover");
  from.style.viewTransitionName = "np-art";
  np.style.viewTransitionName = "np-sheet";
  const vt = document.startViewTransition(() => {
    from.style.viewTransitionName = "";
    swap();
    (open ? $("np-cover") : $("player-cover")).style.viewTransitionName = "np-art";
  });
  vt.ready.catch(() => {});
  vt.finished.finally(() => {
    $("np-cover").style.viewTransitionName = "";
    $("player-cover").style.viewTransitionName = "";
    np.style.viewTransitionName = "";
  }).catch(() => {});
}

// ---------- the visualizer (a ring of bars around the disc) ----------

let stopRing = null;
const motionOff = window.matchMedia("(prefers-reduced-motion: reduce)");
function refreshVisualizer() {
  const on = !!settings.get("visualizer");
  $("np-viz").setAttribute("aria-pressed", String(on));
  const show = on && !$("nowplaying").hidden && !motionOff.matches && !player.remoteMode;
  if (show && !stopRing) {
    local.enableEngineIfNeeded();
    const np = $("nowplaying");
    stopRing = startRing($("np-viz-ring"), $("np-deck").querySelector(".disc") ?? $("np-deck"), () => (local.engine.active ? local.engine.spectrum() : null),
      () => getComputedStyle(np).getPropertyValue("--album-strong").trim() || getComputedStyle(np).color);
  } else if (!show && stopRing) { stopRing(); stopRing = null; }
}
$("np-viz").addEventListener("click", () => {
  settings.set({ visualizer: !settings.get("visualizer") });
  refreshVisualizer();
  toast(settings.get("visualizer") ? "Visualizer on" : "Visualizer off");
});

// Start and stop with Now Playing itself (it opens and closes with an animation).
new MutationObserver(refreshVisualizer).observe($("nowplaying"), { attributes: true, attributeFilter: ["hidden"] });

function openNowPlaying() {
  if (!player.current || !$("nowplaying").hidden) return;
  setNpLyrics(!!store.get("npLyrics", false), true);
  morphNowPlaying(true);
  setTimeout(() => $("np-close").focus({ preventScroll: true }), 50);
}
function closeNowPlaying(animate = true) {
  if ($("nowplaying").hidden) return;
  if (stopRing) { stopRing(); stopRing = null; }
  if (video.active && !$("np-video").hidden) video.stop(true);
  npLyricsOff?.();
  npLyricsOff = null;
  if (animate) morphNowPlaying(false);
  else { $("nowplaying").hidden = true; document.body.classList.remove("np-open"); }
}
$("open-now").addEventListener("click", openNowPlaying);
$("np-close").addEventListener("click", () => closeNowPlaying());
$("nowplaying").addEventListener("click", (e) => {
  if (e.target.closest("a[href]")) closeNowPlaying(false);
});

// Swipe down on now playing to close it.
let touchY = null;
$("nowplaying").addEventListener("touchstart", (e) => {
  touchY = $("nowplaying").scrollTop <= 0 && !e.target.closest("input") ? e.touches[0].clientY : null;
}, { passive: true });
$("nowplaying").addEventListener("touchend", (e) => {
  if (touchY != null && e.changedTouches[0].clientY - touchY > 90) closeNowPlaying();
  touchY = null;
});

document.addEventListener("keydown", (e) => {
  if (e.target.closest?.("input, textarea, .menu") || e.metaKey || e.ctrlKey || e.altKey) return;
  if (e.key === "Escape") closeNowPlaying();
  else if (parseRoute().name === "wrapped" && !e.shiftKey && (e.key === "ArrowRight" || e.key === "ArrowLeft")) wrappedStep(view, e.key === "ArrowRight" ? 1 : -1);
  else if (e.key === " " && !e.target.closest?.("button, a, .track-row")) { e.preventDefault(); transport.toggle(); }
  else if (e.key === "ArrowRight" && e.shiftKey) transport.next();
  else if (e.key === "ArrowLeft" && e.shiftKey) transport.prev();
  else if (e.key === "ArrowRight") transport.seek(transport.position + 10);
  else if (e.key === "ArrowLeft") transport.seek(transport.position - 10);
  else if (e.key === "/") { e.preventDefault(); location.hash = "#/search"; }
});

matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { syncPlayer(); render(); });

// ---------- lyrics, queue and devices buttons ----------

// Lyrics, Queue and Mixer in the player bar open their page, or go back if it's showing.
document.querySelectorAll(".route-toggle").forEach((a) => a.addEventListener("click", (e) => {
  if (parseRoute().name !== a.dataset.route) return;
  e.preventDefault();
  if (navDepth > 0) history.back();
  else location.hash = "#/";
}));

// Lyrics inside Now Playing take the place of the disc.
let npLyricsOff = null;
function setNpLyrics(on, mount = !$("nowplaying").hidden) {
  store.set("npLyrics", on);
  $("np-lyrics-btn").setAttribute("aria-pressed", String(on));
  $("np-lyrics").hidden = !on;
  $("np-deck").hidden = on;
  $("nowplaying").classList.toggle("lyrics-on", on);
  npLyricsOff?.();
  npLyricsOff = on && mount ? mountLyrics($("np-lyrics-inner"), $("np-lyrics"), player) : null;
}
$("np-lyrics-btn").addEventListener("click", () => setNpLyrics($("np-lyrics").hidden));

const KIND_ICON = { computer: "i-dev-computer", phone: "i-dev-phone", tablet: "i-dev-tablet", tv: "i-dev-tv", speaker: "i-dev-speaker" };

function syncDevices() {
  const remote = player.remoteMode;
  const active = player.activeDevice;
  const name = remote ? (active?.name ?? "another device") : "";
  $("player-device").hidden = !remote;
  $("player").classList.toggle("remote", remote);
  $("player-device-name").textContent = remote ? `Playing on ${name}` : "";
  $("np-device-name").textContent = remote ? `Playing on ${name}` : "";
  document.querySelectorAll(".devices-btn").forEach((b) => {
    b.classList.toggle("on", remote);
    b.title = remote ? `Playing on ${name}` : "Play on another device";
  });
}
player.addEventListener("devices", syncDevices);

function openDevices(at) {
  const self = player.self;
  const others = player.devices.filter((d) => d.id !== player.selfId);
  const status = (d) => d.id === player.activeId ? (player.playing ? "Playing now" : "Paused") : "";
  const list = [self, ...others].map((d) => {
    const mine = d.id === player.selfId;
    const st = status(d);
    return {
      label: d.name,
      sub: mine ? (st ? `This device, ${st.toLowerCase()}` : "This device") : st,
      icon: KIND_ICON[d.kind] ?? "i-dev-computer",
      current: d.id === player.activeId || (mine && !player.activeId),
      run: () => player.transferTo(d.id),
    };
  });
  const note = !player.connected
    ? "Can’t reach the server right now, so other devices aren’t shown."
    : !others.length ? "Open Shelf on another phone, computer or TV and it shows up here. Pick it to move the music there." : "";
  // Playing somewhere else: its volume, right here (in the device picker).
  const remote = player.remoteMode && player.activeDevice;
  const footer = remote ? `
    <div class="menu-volume">
      <svg aria-hidden="true"><use href="#i-volume"/></svg>
      <input type="range" class="range" min="0" max="1" step="0.01" aria-label="Volume on ${esc(remote.name)}">
      <output></output>
    </div>` : "";
  openMenu({
    at, heading: "Play on", items: list, note, header: { title: "Play on" }, footer,
    onMount: (menu) => {
      const range = menu.querySelector(".menu-volume input");
      if (!range) return;
      const show = (v) => {
        range.value = String(v);
        range.style.setProperty("--pct", `${v * 100}%`);
        range.setAttribute("aria-valuetext", `${Math.round(v * 100)}%`);
        menu.querySelector(".menu-volume output").textContent = `${Math.round(v * 100)}%`;
        menu.querySelector(".menu-volume use").setAttribute("href", v === 0 ? "#i-mute" : "#i-volume");
      };
      show(player.volume);
      let held = false;
      range.addEventListener("pointerdown", () => { held = true; });
      range.addEventListener("change", () => { held = false; });
      range.addEventListener("input", () => { player.setVolume(Number(range.value)); show(Number(range.value)); syncVolume(); });
      const follow = () => { if (!held && range.isConnected) show(player.volume); };
      player.addEventListener("state", follow);
      const gone = new MutationObserver(() => {
        if (!range.isConnected) { player.removeEventListener("state", follow); gone.disconnect(); }
      });
      gone.observe(menu.parentElement, { childList: true });
    },
  });
}
for (const id of ["btn-devices", "btn-devices-mini", "np-devices"]) {
  $(id).addEventListener("click", (e) => { e.stopPropagation(); openDevices($(id)); });
}

// ---------- drag and drop: songs and albums onto playlists, reordering a playlist ----------

const DRAG_TYPE = "application/x-shelf";
let dragging = null; // what's being dragged: { trackIds?, albumId?, entryIndex?, playlistId?, label }

// Rows become draggable when a mouse presses them (not on touch screens, where a long
// press opens the menu instead).
document.addEventListener("pointerdown", (e) => {
  if (e.pointerType !== "mouse") return;
  const row = e.target.closest?.(".track-row[data-track]");
  if (row && !row.draggable) row.draggable = true;
}, true);

document.addEventListener("dragstart", (e) => {
  const row = e.target.closest?.(".track-row[data-track]");
  const album = e.target.closest?.(".album-card[data-album], .lib-item[data-album]");
  if (row) {
    const i = Number(row.dataset.index);
    const inPlaylist = row.dataset.entry && parseRoute().name === "playlist" && ctx.context?.canEdit;
    const t = Number.isFinite(i) && !row.dataset.queueIndex ? ctx.tracks[i] : null;
    dragging = {
      trackIds: [Number(row.dataset.track)],
      // Album pages list numbers, not covers: fall back to the song's album cover.
      cover: row.querySelector(".case img")?.currentSrc || (t?.cover ? coverUrl(t.albumId, t.cover, 160) : null),
      label: t?.title ?? row.querySelector(".t-title")?.textContent ?? "1 song",
      ...(inPlaylist ? { entryIndex: i, playlistId: parseRoute().id } : {}),
    };
  } else if (album) {
    dragging = {
      albumId: Number(album.dataset.album),
      cover: album.querySelector(".case img")?.currentSrc || null,
      label: album.dataset.title ?? album.querySelector(".card-title")?.textContent ?? "Album",
    };
  } else {
    return;
  }
  e.dataTransfer.effectAllowed = "copyMove";
  e.dataTransfer.setData(DRAG_TYPE, JSON.stringify(dragging));
  e.dataTransfer.setData("text/plain", dragging.label);
  // A small card as the drag image: the cover and the name.
  const ghost = document.createElement("div");
  ghost.className = "drag-ghost";
  ghost.innerHTML = `${dragging.cover ? `<img src="${esc(dragging.cover)}" alt="">` : ""}<span>${esc(dragging.label)}</span>`;
  document.body.append(ghost);
  e.dataTransfer.setDragImage(ghost, -10, -10);
  setTimeout(() => ghost.remove(), 0);
  document.body.classList.add("is-dragging");
});
document.addEventListener("dragend", () => {
  dragging = null;
  document.body.classList.remove("is-dragging");
  document.querySelectorAll(".drop-target, .drop-above, .drop-below").forEach((el) => el.classList.remove("drop-target", "drop-above", "drop-below"));
});

const dropPlaylist = (e) => e.target.closest?.(".lib-item[data-playlist], .pl-card[data-playlist]");
const dropRow = (e) => dragging?.entryIndex != null && parseRoute().name === "playlist" && parseRoute().id === dragging.playlistId
  ? e.target.closest?.(".pl-tracks .track-row[data-entry]") : null;

document.addEventListener("dragover", (e) => {
  if (!dragging) return;
  const pl = dropPlaylist(e);
  const row = dropRow(e);
  document.querySelectorAll(".drop-target, .drop-above, .drop-below").forEach((el) => {
    if (el !== pl && el !== row) el.classList.remove("drop-target", "drop-above", "drop-below");
  });
  if (pl) {
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
    pl.classList.add("drop-target");
  } else if (row) {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    const r = row.getBoundingClientRect();
    const below = e.clientY > r.top + r.height / 2;
    row.classList.toggle("drop-below", below);
    row.classList.toggle("drop-above", !below);
  }
});

document.addEventListener("drop", async (e) => {
  if (!dragging) return;
  const d = dragging;
  const pl = dropPlaylist(e);
  const row = dropRow(e);
  if (!pl && !row) return;
  e.preventDefault();
  try {
    if (pl) {
      const pid = Number(pl.dataset.playlist);
      const flight = flyInto(e.clientX, e.clientY, d.cover, pl);
      const ids = d.trackIds ?? (await api.album(d.albumId)).tracks.map((t) => t.id);
      const r = await api.addToPlaylist(pid, ids);
      await flight;
      await library?.loading; // the library redraws with the new song count first
      bumpPlaylist(pid);
      toast(`Added to ${r.name}`);
      if (parseRoute().name === "playlist" && parseRoute().id === r.id) await redrawPlaylist();
    } else {
      const to = Number(row.dataset.index) + (row.classList.contains("drop-below") ? 1 : 0);
      const target = to > d.entryIndex ? to - 1 : to;
      if (target !== d.entryIndex) await movePlaylistEntry(d.entryIndex, target);
    }
  } catch (err) {
    toast(err.message);
  }
});

// ---------- resizing the side panels ----------

const LIB = { min: 200, max: 480, collapseBelow: 150, def: 300, key: "libWidth", prop: "--lib-open-w" };
const NPV = { min: 280, max: 560, def: 340, key: "npvWidth", prop: "--npv-open-w" };

function setPanelWidth(spec, w) {
  const app = $("app");
  const clamped = Math.round(Math.max(spec.min, Math.min(spec.max, w)));
  app.style.setProperty(spec.prop, `${clamped}px`);
  store.set(spec.key, clamped);
  return clamped;
}
for (const spec of [LIB, NPV]) {
  const saved = Number(store.get(spec.key, 0));
  if (saved) $("app").style.setProperty(spec.prop, `${saved}px`);
}

function makeResizer(handle, spec, fromLeft) {
  const app = $("app");
  const collapse = (on) => { if (on !== app.classList.contains("lib-collapsed")) $("lib-collapse").click(); };
  handle.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    handle.setPointerCapture(e.pointerId);
    document.body.classList.add("is-resizing");
    const box = app.getBoundingClientRect();
    const move = (ev) => {
      const w = fromLeft ? ev.clientX - box.left - 8 : box.right - ev.clientX - 8;
      if (spec === LIB) {
        // Narrow enough and the library folds down to just covers.
        if (w < spec.collapseBelow) { collapse(true); return; }
        collapse(false);
      }
      // Keep the main view at least 420 px wide.
      const room = box.width - 420 - (spec === LIB ? (app.classList.contains("npv-open") ? $("npv").offsetWidth : 0) : $("library").offsetWidth);
      setPanelWidth(spec, Math.min(w, room));
    };
    const up = () => {
      handle.removeEventListener("pointermove", move);
      document.body.classList.remove("is-resizing");
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", up, { once: true });
    handle.addEventListener("pointercancel", up, { once: true });
  });
  handle.addEventListener("dblclick", () => {
    if (spec === LIB) collapse(false);
    setPanelWidth(spec, spec.def);
  });
  handle.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const cur = spec === LIB ? $("library").offsetWidth : $("npv").offsetWidth;
    const step = (e.key === "ArrowRight") === fromLeft ? 16 : -16;
    if (spec === LIB && app.classList.contains("lib-collapsed")) { if (step > 0) collapse(false); return; }
    setPanelWidth(spec, cur + step);
  });
}
makeResizer($("resize-lib"), LIB, true);
makeResizer($("resize-npv"), NPV, false);
new MutationObserver(() => { $("resize-npv").hidden = $("npv").hidden; }).observe($("npv"), { attributes: true, attributeFilter: ["hidden"] });

// ---------- music videos ----------

const video = new VideoMode(local);
let videoFor = { trackId: null, videoId: null }; // the video found for the current song

/** Look up the current song's video and show the "Switch to video" buttons if there is one. */
async function findVideo() {
  const t = player.current;
  videoFor = { trackId: t?.id ?? null, videoId: null };
  showVideoButtons();
  if (!t || player.remoteMode) return;
  const v = await api.video(t.id).catch(() => null);
  if (player.current?.id !== t.id) return;
  videoFor = { trackId: t.id, videoId: v?.found ? v.videoId : null };
  showVideoButtons();
}

function showVideoButtons() {
  const ok = !!videoFor.videoId && videoFor.trackId === player.current?.id && !player.remoteMode && !youTubeOnly().has(videoFor.videoId);
  $("np-video-btn").hidden = !ok;
  $("np-video-btn").setAttribute("aria-pressed", String(video.active && !$("np-video").hidden));
  panel?.setVideo(ok && !video.active ? videoFor.videoId : null);
}

/** Remember that a video only plays on YouTube, and turn its cards into links there. */
function markYouTubeOnly(id) {
  const kept = youTubeOnlyList().filter(([x]) => x !== id).slice(-199);
  store.set("ytOnly", [...kept, [id, Date.now()]]);
  document.querySelectorAll(`.vcard[data-video="${CSS.escape(id)}"]`).forEach((card) => {
    card.outerHTML = videoCard({ videoId: id, title: card.dataset.title ?? "", duration: Number(card.dataset.duration) || null });
  });
  document.querySelectorAll(`.npv-vcard[data-video="${CSS.escape(id)}"]`).forEach((card) => {
    const link = Object.assign(document.createElement("a"), {
      className: card.className, href: `https://www.youtube.com/watch?v=${encodeURIComponent(id)}`, target: "_blank", rel: "noopener",
      title: card.title, innerHTML: card.innerHTML,
    });
    link.lastElementChild.textContent = "Plays on YouTube";
    card.replaceWith(link);
  });
}

async function startVideo(where, id = videoFor.videoId, related = false) {
  if (!id) return;
  const host = where instanceof Element ? where : where === "np" ? $("np-video") : $("npv-video");
  if (where === "np") { setNpLyrics(false); $("np-deck").hidden = true; $("nowplaying").classList.add("video-on"); }
  else if (where === "npv") $("npv").classList.add("video-on");
  try {
    await video.start(host, id, related ? 0 : player.position, player.current?.id ?? null, { related });
  } catch (e) {
    toast(e.message);
  }
}

video.addEventListener("change", () => {
  if (!video.active) {
    $("npv").classList.remove("video-on");
    if ($("nowplaying").classList.contains("video-on")) {
      $("nowplaying").classList.remove("video-on");
      if (!store.get("npLyrics", false)) $("np-deck").hidden = false;
    }
  }
  showVideoButtons();
  syncPlayer();
});
video.addEventListener("time", () => syncTime());
video.addEventListener("ended", () => player.next(true)); // the song was paused for the video: not a skip
video.addEventListener("error", () => {
  // 101/150: the video's owner only lets it play on YouTube itself (or on sites they've
  // approved). Remember that, and make its cards open YouTube instead.
  if ([101, 150].includes(video.lastError) && video.lastVideoId) {
    markYouTubeOnly(video.lastVideoId);
    toast("This video only plays on YouTube. Select it again to watch it there.", 4500);
  } else {
    toast(player.playing ? "YouTube couldn’t play this video here, so the song carries on" : "YouTube couldn’t play this video here");
  }
});
$("np-video-btn").addEventListener("click", () => (video.active ? video.stop(true) : startVideo("np")));
player.addEventListener("track", () => {
  // A new song (autoplay, another device, the queue) ends the video of the last one.
  if (video.active && video.trackId !== player.current?.id) video.stop(false);
  findVideo();
});
player.addEventListener("devices", () => { if (player.remoteMode && video.active) video.stop(false); showVideoButtons(); });

// ---------- top bar, library and side panel (wide screens) ----------

$("nav-back").addEventListener("click", () => history.back());
$("nav-fwd").addEventListener("click", () => history.forward());
$("btn-fullscreen").addEventListener("click", () => openNowPlaying());

// The search box in the top bar drives the Search page.
let topSearchTimer;
$("top-search").addEventListener("input", (e) => {
  clearTimeout(topSearchTimer);
  topSearchTimer = setTimeout(() => {
    const q = e.target.value.trim();
    const target = q ? `#/search?q=${encodeURIComponent(q)}` : "#/search";
    // Typing more replaces the search in history instead of adding a step per letter.
    if (parseRoute().name === "search") location.replace(target);
    else location.hash = target;
  }, 160);
});
$("top-search").addEventListener("focus", () => { if (parseRoute().name !== "search" && !$("top-search").value) location.hash = "#/search"; });
window.addEventListener("hashchange", () => {
  const r = parseRoute();
  if (r.name === "search") { if (document.activeElement !== $("top-search")) $("top-search").value = r.q; }
  else $("top-search").value = "";
});

let library = null;
let panel = null;
function mountShell() {
  if (library) return;
  library = mountLibrary($("library"), player);
  likes.load();
  panel = mountPanel(player, {
    fallbackQueue: () => { location.hash = parseRoute().name === "queue" ? "#/" : "#/queue"; },
    onVideo: () => startVideo("npv"),
    onRelated: (id) => startVideo("npv", id, true),
    onClose: () => { if (video.active && !$("npv-video").hidden) video.stop(true); },
    onAdded: (pid) => { if (parseRoute().name === "playlist" && parseRoute().id === pid) redrawPlaylist(); },
  });
  findVideo();
  const lib = $("library");
  lib.addEventListener("contextmenu", (e) => {
    const item = e.target.closest(".lib-item[data-album], .lib-item[data-playlist]");
    if (!item) return;
    e.preventDefault();
    const at = e.clientX || e.clientY ? { x: e.clientX, y: e.clientY } : item;
    if (item.dataset.playlist) playlistMenu(Number(item.dataset.playlist), at);
    else albumMenu(item, at);
  });
  lib.addEventListener("dblclick", (e) => {
    const item = e.target.closest(".lib-item[data-album]");
    if (item) runAction("play-album", { dataset: { id: item.dataset.album } }).catch((err) => toast(err.message));
  });
  $("npv").addEventListener("contextmenu", (e) => {
    if (menuFor(e.target, e.clientX || e.clientY ? { x: e.clientX, y: e.clientY } : e.target)) e.preventDefault();
  });
}

// ---------- sign in ----------

let loginMode = "signin";
let sleepMounted = false;
let djShow = null; // or "setup": the server has no accounts yet

function showLogin({ setup = false, editServer = false } = {}) {
  closeMenu();
  local.pause?.();
  player.stop();
  clearNative();
  session.user = null;
  applyUser();
  loginMode = setup ? "setup" : "signin";
  $("app").hidden = true;
  $("login").hidden = false;
  $("login-title").textContent = setup ? "Set up Shelf" : "Shelf";
  $("login-lead").hidden = !setup;
  $("login-lead").textContent = setup
    ? "Create the admin account. You can add everyone else from the admin dashboard once you’re in." : "";
  document.querySelectorAll(".setup-only").forEach((n) => { n.hidden = !setup; });
  $("login-password").autocomplete = setup ? "new-password" : "current-password";
  $("login-submit").textContent = setup ? "Create account" : "Sign in";
  $("login-error").textContent = "";
  $("login-password").value = "";
  $("login-confirm").value = "";
  $("server-url").textContent = currentServer().replace(/^https?:\/\//, "");
  showServerEdit(editServer);
  if (!editServer) ($("login-username").value ? $("login-password") : $("login-username")).focus();
}

function showServerEdit(on) {
  $("server-box").hidden = on;
  $("server-edit").hidden = !on;
  $("login-fields").hidden = on;
  $("login-submit").hidden = on;
  if (on) {
    $("login-server").value = currentServer().replace(/^https?:\/\//, "");
    $("login-server").focus();
    $("login-server").select();
  }
}

async function connectServer() {
  const btn = $("server-go");
  $("login-error").textContent = "";
  btn.disabled = true;
  btn.textContent = "Connecting…";
  try {
    const moved = await switchServer($("login-server").value);
    if (!moved) showServerEdit(false);
  } catch (err) {
    $("login-error").textContent = err.message;
  } finally {
    btn.disabled = false;
    btn.textContent = "Connect";
  }
}

$("server-change").addEventListener("click", () => { $("login-error").textContent = ""; showServerEdit(true); });
$("server-go").addEventListener("click", connectServer);
$("login-server").addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); connectServer(); }
  if (e.key === "Escape" && android == null) showServerEdit(false);
});

/** Show or hide the parts only admins get. */
function applyUser() {
  const admin = !!session.user?.admin;
  $("admin-link").hidden = !admin;
  document.body.classList.toggle("is-admin", admin);
}

async function showApp() {
  $("login").hidden = true;
  $("app").hidden = false;
  applyUser();
  android?.signedIn?.(session.user?.username ?? "");
  syncPlayer();
  syncTime();
  syncDevices();
  mountShell();
  if (!embedded) player.start();
  mountNative(player);
  if (!sleepMounted) {
    if (!session.features) session.features = (await api.session().catch(() => ({}))).features ?? {};
    features.dj = !!session.features.dj; // the DJ is on the shelf unless an admin turns it on
    mountSleep(player, local);
    if (features.dj) djShow = mountDJ(player, local);
    sleepMounted = true;
  }
  await render();
  firstRender = false;
  if (!isOffline) cameOnline().catch(() => {});
  if (!isOffline) maybeShowWhatsNew({ version: session.version, admin: !!session.user?.admin });
}

setUnauthorizedHandler(() => showLogin());

$("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!$("server-edit").hidden) return connectServer();
  const err = $("login-error");
  const username = $("login-username").value.trim();
  const password = $("login-password").value;
  err.textContent = "";
  if (!username) { err.textContent = "Enter your username."; $("login-username").focus(); return; }
  if (!password) { err.textContent = "Enter your password."; $("login-password").focus(); return; }
  if (loginMode === "setup" && password !== $("login-confirm").value) {
    err.textContent = "The two passwords don’t match.";
    $("login-confirm").focus();
    return;
  }
  const btn = $("login-submit");
  btn.disabled = true;
  try {
    const r = loginMode === "setup" ? await api.setup(username, password) : await api.login(username, password);
    session.user = r.user;
    store.set("lastUser", username);
    store.set("lastUserInfo", r.user);
    if (firstRender) await showApp();
    else location.reload(); // a different person: start clean
  } catch (ex) {
    err.textContent = ex.status === 401 ? "That username and password didn’t match. Try again." : ex.message;
  } finally {
    btn.disabled = false;
  }
});

// ---------- you (phones) ----------

// Phones have no top bar, so Settings, Friend activity and the rest live behind your initials
// at the top of Home, Search, Playlists and Downloads.
const ME_PAGES = new Set(["home", "search", "playlists", "downloads"]);

function addMeButton(route) {
  if (!session.user || !ME_PAGES.has(route.name)) return;
  const head = view.querySelector(".page-head");
  if (!head || head.querySelector(".me-btn")) return;
  const b = document.createElement("button");
  b.className = "me-btn";
  b.type = "button";
  b.dataset.action = "me-menu";
  b.setAttribute("aria-label", `${session.user.username}: settings and more`);
  b.innerHTML = personDisc(session.user.username);
  head.prepend(b);
}

function meMenu(at) {
  const u = session.user;
  if (!u) return;
  const go = (hash) => () => { location.hash = hash; };
  openMenu({
    at,
    header: { art: personDisc(u.username), title: u.username, sub: u.admin ? "Admin" : "Your account" },
    items: [
      { label: "Settings", icon: "i-settings", run: go("#/settings") },
      { label: "Friend activity", icon: "i-people", run: go("#/people") },
      { label: "Downloads", icon: "i-download", run: go("#/downloads") },
      { label: "Not on your shelf", icon: "i-disc", run: go("#/releases") },
      ...(u.admin ? [{ label: "Admin dashboard", icon: "i-admin", run: go("#/admin") }] : []),
      "sep",
      { label: "Sign out", icon: "i-close", run: () => runAction("logout", at).catch((e) => toast(e.message)) },
    ],
  });
}

// ---------- downloads ----------

offline.setQuality(() => settings.get("downloadQuality"));

let dlFrame = 0;
let libDirty = false;
window.addEventListener("downloads-changed", (e) => {
  if (e.detail?.key) libDirty = true; // added or removed (not just progress)
  if (dlFrame) return;
  dlFrame = requestAnimationFrame(() => {
    dlFrame = 0;
    refreshDownloads(document);
    if (libDirty) { libDirty = false; library?.redraw?.(); }
    if (parseRoute().name === "downloads" && !document.querySelector("dialog[open]")) {
      const top = view.scrollTop;
      downloadsView(view).then(() => { view.scrollTop = top; }).catch(() => {});
    }
  });
});
window.addEventListener("downloads-full", () => toast("This device is out of space for downloads. Remove some to download more.", 6000));

/** Bring downloaded playlists and Favourites in line with the server (songs added or removed). */
const syncTimers = new Map();
function syncSoon(key, ms = 1500) {
  clearTimeout(syncTimers.get(key));
  syncTimers.set(key, setTimeout(() => syncDownload(key).catch(() => {}), ms));
}
async function syncDownload(key) {
  if (isOffline || !offline.isSaved(key)) return;
  const [kind, id] = key.split(":");
  const data = kind === "liked" ? await api.likes() : kind === "playlist" ? await api.playlist(Number(id)) : await api.album(Number(id));
  if (!isOffline) await offline.refresh(key, data);
}
window.addEventListener("playlists-changed", () => {
  for (const c of offline.list()) if (c.kind === "playlist") syncSoon(c.key);
});

/** Back online: send listens made offline, catch downloads up, and show the full app again. */
async function cameOnline() {
  const sent = await offline.flushPlays((id, at) => api.playedAt(id, at));
  if (sent) toast(`Added ${plural(sent, "song")} you played offline to your history`);
  for (const c of offline.list()) syncSoon(c.key, 500);
  offline.retry();
}
window.addEventListener("connection-changed", (e) => {
  if (!e.detail.offline) { cameOnline().catch(() => {}); library?.refresh(); }
  if (["home", "downloads"].includes(parseRoute().name)) render();
});

/** No connection at start, but there are downloads: open the app with them. */
async function startOffline() {
  await offline.ready;
  if (!offline.list().length) return false;
  session.user = store.get("lastUserInfo", null);
  document.body.classList.add("offline");
  if (!["album", "playlist", "liked", "downloads"].includes(parseRoute().name)) location.hash = "#/downloads";
  await showApp();
  // Keep checking, and switch over once the server is back.
  const timer = setInterval(async () => {
    const s = await api.session().catch(() => null);
    if (s) { clearInterval(timer); location.reload(); }
  }, 15000);
  return true;
}

// ---------- boot ----------

(async () => {
  try {
    await claimHandoff();
    const s = await api.session();
    if (await moveToSecure(s)) return;
    session.user = s.user;
    session.version = s.version;
    session.features = s.features;
    if (s.user) store.set("lastUserInfo", s.user);
    $("login-username").value = store.get("lastUser", "");
    if (!s.signedIn) showLogin({ setup: s.setup });
    else await showApp();
  } catch {
    if (await startOffline().catch(() => false)) return;
    document.body.innerHTML = `<div class="login"><div class="login-card"><h1>Shelf</h1><p>Can’t reach the server. Check it’s running and that you’re on the right address, then reload.</p>${android ? `<button class="btn btn-primary" type="button" onclick="(window.ShelfAndroid || window.ShelfDesktop).changeServer()">Change server</button>` : ""}</div></div>`;
  }
  if ("serviceWorker" in navigator && window.isSecureContext) {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  }
})();

// ---------- party mode: playing along as a guest ----------

// While you're at someone's party with Play here on, this device plays what they play, in step,
// wherever you are in the app. (Your own party plays on your playing device as usual.)
setInterval(async () => {
  const join = store.get("party", null);
  if (!join?.playHere || document.hidden && !player.playing) return;
  let s;
  try { s = await api.party(join.host); } catch (e) {
    if (e.status === 404) { store.set("party", null); toast("The party has ended"); }
    return;
  }
  if (s.isHost) return;
  const step = followHost(
    { trackId: player.current?.id ?? null, position: player.position, playing: player.playing },
    { trackId: s.nowPlaying?.id ?? null, position: s.position, playing: s.playing });
  if (step.load && s.nowPlaying) {
    player.playList([s.nowPlaying, ...s.upNext], 0, { context: { label: `${s.host.username}’s party`, href: `#/party/${join.host}` }, startAt: step.seekTo ?? 0 });
    if (!s.playing) setTimeout(() => player.pause(), 300);
    return;
  }
  if (step.seekTo != null) player.seek(step.seekTo);
  if (step.play === true) player.play();
  else if (step.play === false) player.pause();
}, 3000);
