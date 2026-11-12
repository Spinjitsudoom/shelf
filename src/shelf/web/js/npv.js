// The right-hand panel on wide screens: what's playing (with the album and what's next),
// or the queue. The player bar's Now Playing and Queue buttons switch between them.
// A playlist's "Add" button opens it as "Add to playlist": search, suggestions, recently
// played and liked songs, each a tap away from the playlist.

import { api } from "./api.js";
import { likeButton, likes } from "./likes.js";
import { attachQueueDrag, gripHtml, queueDragging } from "./queuedrag.js";
import { mountTransitionEditor } from "./transition-editor.js";
import { caseHtml, esc, fmtLength, fmtTime, keyBadge, plural, quality, store, toast } from "./util.js";
import { artistHref, artistLinks, youTubeOnly } from "./views.js";

const ADD_TABS = { suggested: "Suggested songs", recent: "Recently played", liked: "Favourites" };

const ytThumb = (id) => `https://i.ytimg.com/vi/${encodeURIComponent(id)}/mqdefault.jpg`;

const STREAM_LABEL = { low: "AAC 96", normal: "AAC 128", high: "AAC 192", veryhigh: "AAC 320" };
const WIDE = matchMedia("(min-width: 1101px)");
const QUEUE_LIMIT = 80;

/**
 * Mount the panel. `fallbackQueue()` runs when the screen is too narrow for the panel and
 * the queue is asked for (it opens the Queue page instead).
 */
export function mountPanel(player, { fallbackQueue, onVideo = () => {}, onRelated = () => {}, onClose = () => {}, onAdded = () => {} }) {
  const app = document.getElementById("app");
  const panel = document.getElementById("npv");
  const body = document.getElementById("npv-body");
  const ctx = document.getElementById("npv-context");
  const btnNow = document.getElementById("btn-npv");
  const btnQueue = document.getElementById("btn-queue");
  let mode = store.get("npvMode", "now"); // "now" | "queue" | null (closed)
  let drawn = "";
  let videoId = null; // set when the current song has a music video
  let add = null; // { pid, name, tab, query, seed, before } while adding to a playlist
  let editor = null; // { before, handle } while editing a Mix transition

  function apply() {
    const open = !!mode && WIDE.matches;
    if (!open && editor) closeEditor();
    panel.classList.toggle("editing", !!editor);
    if (!open) onClose();
    panel.hidden = !open;
    app.classList.toggle("npv-open", open);
    if (!open && add) { mode = add.before; add = null; }
    btnNow.setAttribute("aria-pressed", String(open && mode === "now"));
    btnQueue.setAttribute("aria-pressed", String(open && mode === "queue"));
    btnNow.hidden = !WIDE.matches;
    drawn = "";
    render();
  }

  function setMode(m) {
    mode = m;
    add = null;
    store.set("npvMode", m);
    apply();
  }

  function toggle(m) {
    if (add) { const before = add.before; add = null; mode = before; }
    if (!WIDE.matches) {
      if (m === "queue") fallbackQueue();
      return;
    }
    setMode(mode === m ? null : m);
  }

  const badge = (t) => {
    const streamed = STREAM_LABEL[player.currentQuality];
    const q = streamed ? null : quality([t]);
    const text = streamed ?? q?.short;
    return text ? `<span class="badge${q?.lossless ? " lossless" : ""}" title="${esc(streamed ? "Streaming a smaller copy" : q?.detail ?? "")}">${esc(text)}</span>` : "";
  };

  const row = (t, qi, current, movable = false) => `
    <div class="track-row with-art npv-row${current ? ` playing${player.playing ? "" : " paused"}` : ""}" data-queue-index="${qi}" data-track="${t.id}" tabindex="0">
      ${caseHtml(t, { size: 160, cls: "case-sm", sizes: "44px" })}
      <span class="t-main"><span class="t-title">${esc(t.title)}</span><span class="t-sub">${esc(t.artist)}</span></span>
      <span>${movable ? gripHtml(t, qi) : ""}</span>
      <span class="dur">${fmtTime(t.duration)}</span>
    </div>`;

  function renderNow(t) {
    const from = player.context ?? { label: t.album, href: `#/album/${t.albumId}` };
    ctx.textContent = from.label;
    ctx.href = from.href;
    const nxt = player.nextTrack;
    const nextIndex = nxt ? player.queue.indexOf(nxt) : -1;
    body.innerHTML = `
      <div class="npv-art-wrap">
        <a class="npv-art" href="#/album/${t.albumId}" aria-label="Go to ${esc(t.album)}">
          ${caseHtml(t, { size: 640, cls: "case-lg", lazy: false, sizes: "340px" })}
        </a>
        <button class="video-btn" type="button" data-npv="video"${videoId ? "" : " hidden"}><svg><use href="#i-video"/></svg>Switch to video</button>
      </div>
      <div class="npv-meta">
        <div class="npv-names">
          <a class="npv-title" href="#/album/${t.albumId}">${esc(t.title)}</a>
          <span class="npv-artist">${t.kind === "episode" ? `<a href="#/podcast/${t.podcastId}">${esc(t.album)}</a>` : artistLinks(t.artist, t.artists)}</span>
        </div>
        <span class="npv-meta-end"><span id="npv-badge">${badge(t)}</span>${t.kind === "episode" ? "" : likeButton(t)}</span>
      </div>
      <section class="npv-related" id="npv-related" hidden></section>
      <section class="npv-artist" id="npv-artist" hidden></section>
      <section class="npv-card">
        <div class="npv-card-head">
          <h3>${player.repeat === "one" ? "Repeating this song" : "Next in queue"}</h3>
          <button class="npv-link" type="button" data-npv="queue">Open queue</button>
        </div>
        ${nxt && player.repeat !== "one" ? row(nxt, nextIndex, false) : player.repeat === "one" ? "" : `<p class="npv-note">Nothing queued after this song.</p>`}
      </section>
      <section class="npv-card" id="npv-album"></section>`;
    const artist = t.albumArtist || t.artist;
    if (!player.remoteMode) {
      api.artistVideos(artist).then((list) => {
        const slot = body.querySelector("#npv-related");
        if (!slot || player.current?.id !== t.id) return;
        const blocked = youTubeOnly();
        const shown = list.filter((v) => v.videoId !== videoId).slice(0, 8);
        if (!shown.length) return;
        slot.hidden = false;
        slot.innerHTML = `
          <h3 class="npv-h">Related music videos</h3>
          <div class="npv-vrow">${shown.map((v) => blocked.has(v.videoId) ? `
            <a class="npv-vcard" href="https://www.youtube.com/watch?v=${encodeURIComponent(v.videoId)}" target="_blank" rel="noopener" title="${esc(v.title)}">
              <span class="npv-thumb"><img src="${ytThumb(v.videoId)}" alt="" loading="lazy"></span>
              <b>${esc(v.title)}</b><span>Plays on YouTube</span>
            </a>` : `
            <button class="npv-vcard" type="button" data-related="${esc(v.videoId)}" data-video="${esc(v.videoId)}" title="${esc(v.title)}">
              <span class="npv-thumb"><img src="${ytThumb(v.videoId)}" alt="" loading="lazy"></span>
              <b>${esc(v.title)}</b><span>${esc(v.artist)}</span>
            </button>`).join("")}</div>`;
      }).catch(() => {});
    }
    api.artistAbout(artist).then((a) => {
      const slot = body.querySelector("#npv-artist");
      if (!slot || player.current?.id !== t.id || !a.found) return;
      slot.hidden = false;
      slot.innerHTML = `
        <a class="npv-artist-card" href="${artistHref(artist)}">
          <span class="npv-artist-photo"${a.image ? ` style="background-image:url('${esc(a.image)}')"` : ""}><span>About the artist</span></span>
          <span class="npv-artist-text">
            <b>${esc(artist)}</b>
            ${a.description ? `<span class="npv-artist-desc">${esc(a.description)}</span>` : ""}
            <span class="npv-artist-bio">${esc(a.extract)}</span>
          </span>
        </a>`;
    }).catch(() => {});
    api.album(t.albumId).then((a) => {
      const slot = body.querySelector("#npv-album");
      if (!slot || player.current?.albumId !== a.id) return;
      const q = quality(a.tracks);
      slot.innerHTML = `
        <div class="npv-card-head"><h3>About the album</h3></div>
        <a class="npv-album" href="#/album/${a.id}">
          ${caseHtml(a, { size: 160, cls: "case-sm", sizes: "64px" })}
          <span><b>${esc(a.title)}</b><span>${esc(a.artist)}</span></span>
        </a>
        <p class="npv-facts">${esc([a.year, plural(a.trackCount, "song"), fmtLength(a.duration)].filter(Boolean).join(", "))}${a.genre ? `<br>${esc(a.genre)}` : ""}${q ? `<br>${esc(q.label)}, ${esc(q.detail)}` : ""}</p>`;
    }).catch(() => {});
  }

  function renderQueue(t) {
    ctx.textContent = "Queue";
    ctx.removeAttribute("href");
    const next = player.upNext;
    const offset = player.index + 1;
    const from = player.context?.label;
    body.innerHTML = `
      <h3 class="npv-h">Now playing</h3>
      ${row(t, player.index, true)}
      ${next.length ? `<h3 class="npv-h">${from ? `Next from: ${esc(from)}` : "Next up"}</h3>
        ${next.slice(0, QUEUE_LIMIT).map((x, i) => (x.autoplay && !next[i - 1]?.autoplay ? `<h3 class="npv-h">Autoplay: similar songs</h3>` : "") + row(x, offset + i, false, true)).join("")}
        ${next.length > QUEUE_LIMIT ? `<a class="npv-more" href="#/queue">${plural(next.length - QUEUE_LIMIT, "more song")} in the queue</a>` : ""}`
        : `<p class="npv-note">That’s the last song${player.repeat === "all" ? ". Repeat is on, so the queue starts over after it." : "."}</p>`}`;
  }

  // ---- add to playlist ----

  const addRow = (t, added) => `
    <div class="track-row with-art npv-row add-row" data-track="${t.id}">
      ${caseHtml(t, { size: 160, cls: "case-sm", sizes: "44px" })}
      <span class="t-main"><span class="t-title">${esc(t.title)}</span><span class="t-sub">${esc(t.artist)}</span></span>
      <span class="add-facts">${t.bpm ? `<span class="add-bpm">${t.bpm} BPM</span>` : ""}<span class="add-line">${keyBadge(t)}<span class="dur">${fmtTime(t.duration)}</span></span></span>
      <button class="add-btn" type="button" data-add="${t.id}" aria-label="${added ? "Added" : "Add"} ${esc(t.title)}" aria-pressed="${added}"${added ? " disabled" : ""}>
        <svg><use href="#${added ? "i-check" : "i-plus"}"/></svg></button>
    </div>`;

  async function drawAddList() {
    const a = add;
    const list = body.querySelector("#add-list");
    const note = body.querySelector("#add-note");
    if (!a || !list) return;
    let tracks = [];
    let why = "";
    try {
      if (a.query) {
        tracks = (await api.search(a.query)).tracks.slice(0, 30);
        why = tracks.length ? "" : `No songs match “${a.query}”.`;
      } else if (a.tab === "suggested") {
        tracks = await api.recommendations(a.pid, a.seed, 25);
        why = tracks.length ? `Songs that fit ${a.name}` : "Add a few songs and suggestions that fit them show up here.";
      } else if (a.tab === "recent") {
        tracks = await api.recentTracks(40);
        why = tracks.length ? "" : "Songs you play show up here.";
      } else {
        tracks = await api.likes();
        why = tracks.length ? "" : "Songs you’ve liked show up here.";
      }
    } catch (e) { why = e.message; }
    if (add !== a || !body.contains(list)) return;
    note.textContent = why;
    list.innerHTML = tracks.map((t) => addRow(t, a.added.has(t.id))).join("");
  }

  function renderAdd() {
    ctx.textContent = "Add to playlist";
    ctx.removeAttribute("href");
    body.innerHTML = `
      <div class="add-panel">
        <label class="add-search"><span class="sr-only">Search for songs to add</span><svg><use href="#i-search"/></svg>
          <input id="add-search" type="search" placeholder="Search" value="${esc(add.query)}" autocomplete="off"></label>
        <div class="chips add-chips" role="group" aria-label="Show">${Object.entries(ADD_TABS).map(([k, v]) =>
          `<button class="chip" type="button" data-add-tab="${k}" aria-pressed="${!add.query && add.tab === k}">${v}</button>`).join("")}</div>
        <div class="add-note-row"><p class="npv-note" id="add-note"></p>${add.tab === "suggested" && !add.query ? `<button class="npv-link" type="button" data-add-refresh>Refresh</button>` : ""}</div>
        <div id="add-list"></div>
      </div>`;
    let timer;
    body.querySelector("#add-search").addEventListener("input", (e) => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        add.query = e.target.value.trim();
        body.querySelectorAll("[data-add-tab]").forEach((c) => c.setAttribute("aria-pressed", String(!add.query && c.dataset.addTab === add.tab)));
        drawAddList();
      }, 180);
    });
    drawAddList();
  }

  function closeEditor() {
    const e = editor;
    if (!e) return;
    editor = null;
    e.handle?.close();
    mode = e.before;
    panel.classList.remove("editing");
    drawn = "";
    apply();
  }

  function render() {
    if (panel.hidden || editor || queueDragging()) return;
    if (add) {
      const key = `add|${add.pid}`;
      if (drawn !== key) { drawn = key; renderAdd(); }
      return;
    }
    const t = player.current;
    // Redraw only when something shown has changed (state events are frequent).
    const key = [mode, t?.id, player.index, player.playing, player.repeat, player.context?.label,
      mode === "queue" ? player.queue.length + ":" + player.upNext.slice(0, QUEUE_LIMIT).map((x) => x.id).join(",") : player.nextTrack?.id].join("|");
    if (key === drawn) {
      const b = body.querySelector("#npv-badge");
      if (b && t) b.innerHTML = badge(t);
      return;
    }
    const scroll = body.scrollTop;
    drawn = key;
    if (!t) {
      ctx.textContent = mode === "queue" ? "Queue" : "";
      body.innerHTML = `<div class="npv-empty"><strong>Nothing playing</strong>Pick an album to start. What’s playing shows up here.</div>`;
      return;
    }
    if (mode === "queue") renderQueue(t); else renderNow(t);
    body.scrollTop = mode === "queue" ? scroll : 0;
  }

  attachQueueDrag(body, player, { redraw: () => { drawn = ""; render(); } });

  body.addEventListener("click", async (e) => {
    const tab = e.target.closest("[data-add-tab]");
    if (tab && add) {
      add.tab = tab.dataset.addTab;
      add.query = "";
      drawn = "";
      render();
      return;
    }
    if (e.target.closest("[data-add-refresh]") && add) { add.seed++; drawAddList(); return; }
    const plus = e.target.closest("[data-add]");
    if (plus && add) {
      const id = Number(plus.dataset.add);
      plus.disabled = true;
      try {
        const r = await api.addToPlaylist(add.pid, [id]);
        add.added.add(id);
        plus.setAttribute("aria-pressed", "true");
        plus.querySelector("use").setAttribute("href", "#i-check");
        toast(`Added to ${r.name}`);
        onAdded(add.pid);
      } catch (err) { plus.disabled = false; toast(err.message); }
      return;
    }
    if (add) return;
    if (e.target.closest('[data-npv="queue"]')) { setMode("queue"); return; }
    if (e.target.closest('[data-npv="video"]')) { onVideo(); return; }
    const rel = e.target.closest("[data-related]");
    if (rel) { onRelated(rel.dataset.related); return; }
    const r = e.target.closest("[data-queue-index]");
    if (r && !e.target.closest("a")) player.jumpTo(Number(r.dataset.queueIndex));
  });
  body.addEventListener("keydown", (e) => {
    const r = e.target.closest?.("[data-queue-index]");
    if (r && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); player.jumpTo(Number(r.dataset.queueIndex)); }
  });
  document.getElementById("npv-close").addEventListener("click", () => {
    if (add) { const before = add.before; add = null; mode = before; apply(); return; }
    setMode(null);
  });
  btnNow.addEventListener("click", () => toggle("now"));
  btnQueue.addEventListener("click", () => toggle("queue"));
  for (const type of ["track", "state"]) player.addEventListener(type, render);
  WIDE.addEventListener("change", apply);
  apply();
  window.addEventListener("likes-changed", () => { if (add?.tab === "liked" && !add.query) drawAddList(); });
  return {
    render,
    /** Open the transition editor in the panel. False when the screen is too narrow for it. */
    openTransition(opts) {
      if (!WIDE.matches) return false;
      if (editor) closeEditor();
      if (add) { mode = add.before; add = null; }
      editor = { before: mode };
      mode = mode || "now";
      panel.hidden = false;
      app.classList.add("npv-open");
      panel.classList.add("editing");
      editor.handle = mountTransitionEditor(body, {
        ...opts,
        onClose: () => { if (editor) { const before = editor.before; editor = null; mode = before; panel.classList.remove("editing"); drawn = ""; apply(); } },
      });
      return true;
    },
    /** Open the panel to add songs to playlist `pid`. False when the screen is too narrow for it. */
    async openAdd(pid) {
      if (!WIDE.matches) return false;
      const p = await api.playlist(pid).catch(() => null);
      add = { pid, name: p?.name ?? "this playlist", tab: p?.tracks.length ? "suggested" : "recent", query: "", seed: 0,
        added: new Set(), before: add?.before ?? mode };
      mode = "add";
      apply();
      body.querySelector("#add-search")?.focus({ preventScroll: true });
      return true;
    },
    /** Show "Switch to video" over the cover (null hides it). */
    setVideo(id) {
      videoId = id;
      const b = body.querySelector('[data-npv="video"]');
      if (b) b.hidden = !id;
    },
  };
}
