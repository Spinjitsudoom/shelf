// Podcasts (see src/shelf/podcasts.py): follow shows by name or by pasting their link (Podbean,
// Apple Podcasts, a feed...), then play episodes in the ordinary player, which keeps your place.

import { api } from "./api.js";
import { offline } from "./offline.js";
import { caseHtml, esc, fmtLength, fmtTime, plural, toast } from "./util.js";

const day = (ts) => ts ? new Date(ts * 1000).toLocaleDateString(undefined,
  { day: "numeric", month: "short", ...(Date.now() / 1000 - ts > 300 * 86400 ? { year: "numeric" } : {}) }) : "";

/** "12 Nov · 45 min", "12 min left" or "Played". */
function status(e) {
  const when = day(e.published);
  if (e.finished) return [when, "Played"].filter(Boolean).join(" · ");
  if (e.position > 0 && e.duration) return [when, `${fmtLength(Math.max(60, e.duration - e.position))} left`].join(" · ");
  return [when, e.duration ? fmtLength(e.duration) : null].filter(Boolean).join(" · ");
}

/** One episode: what it is, how far you are, play and mark-as-played. `withShow` for mixed lists. */
export function episodeRow(e, i, { withShow = false } = {}) {
  const pct = e.position > 0 && e.duration ? Math.min(100, (e.position / e.duration) * 100) : 0;
  return `
    <li class="ep-row${e.finished ? " finished" : ""}" data-ep="${i}">
      ${withShow ? `<a class="ep-art" href="#/podcast/${e.podcastId}" aria-label="${esc(e.album)}">${caseHtml(e, { size: 160, cls: "case-sm", sizes: "56px" })}</a>` : ""}
      <div class="ep-main">
        <span class="ep-meta">${withShow ? `<a href="#/podcast/${e.podcastId}">${esc(e.album)}</a> · ` : ""}${esc(status(e))}</span>
        <button class="ep-title" type="button" data-ep-more aria-expanded="false">${esc(e.title)}</button>
        ${e.description ? `<p class="ep-desc">${esc(e.description)}</p>` : ""}
        ${pct ? `<span class="ep-progress" aria-hidden="true"><span style="width:${pct.toFixed(1)}%"></span></span>` : ""}
        <div class="ep-tools">
          <button class="icon-btn ep-save" type="button" data-ep-save aria-pressed="${!!e.saved}" title="${e.saved ? "Remove from Your Episodes" : "Save to Your Episodes"}"
            aria-label="${e.saved ? "Remove from Your Episodes" : "Save to Your Episodes"}"><svg><use href="#i-${e.saved ? "saved" : "save"}"/></svg></button>
          <button class="icon-btn dl-btn ep-dl" type="button" data-ep-dl data-dl="episode:${e.episodeId}" aria-pressed="false" aria-label="Download" title="Download"><svg class="dl-ring" viewBox="0 0 36 36" aria-hidden="true">
            <circle class="dl-track" cx="18" cy="18" r="15.5"/><circle class="dl-fill" cx="18" cy="18" r="15.5" pathLength="100"/>
            <path class="dl-arrow" d="M18 11v12m-5-5 5 5 5-5"/></svg></button>
          <button class="icon-btn ep-done" type="button" data-ep-done aria-pressed="${e.finished}" title="${e.finished ? "Mark as not played" : "Mark as played"}"
            aria-label="${e.finished ? "Mark as not played" : "Mark as played"}"><svg><use href="#i-check"/></svg></button>
        </div>
      </div>
      <div class="ep-actions">
        <button class="ep-play" type="button" data-ep-play aria-label="Play ${esc(e.title)}" title="${e.position > 0 && !e.finished ? `Resume at ${fmtTime(e.position)}` : "Play"}"><svg><use href="#i-play"/></svg></button>
      </div>
    </li>`;
}

/** Play, mark and expand in a list of episodes (an array, or a function giving the current
 * one when the list is redrawn in place). `redraw` after marking. */
export function wireEpisodes(list, episodes, player, redraw) {
  list?.addEventListener("click", async (ev) => {
    const row = ev.target.closest("[data-ep]");
    if (!row) return;
    const e = (typeof episodes === "function" ? episodes() : episodes)[Number(row.dataset.ep)];
    if (!e) return;
    if (ev.target.closest("[data-ep-play]")) {
      player.playList([e], 0, { context: { label: e.album, href: `#/podcast/${e.podcastId}` } });
    } else if (ev.target.closest("[data-ep-done]")) {
      try {
        await api.markEpisode(e.episodeId, !e.finished);
        redraw();
      } catch (err) { toast(err.message); }
    } else if (ev.target.closest("[data-ep-save]")) {
      try {
        await saveEpisode(e, !e.saved);
        setSaved(row, e);
      } catch (err) { toast(err.message); }
    } else if (ev.target.closest("[data-ep-dl]")) {
      try {
        await downloadEpisode(e);
        setSaved(row, e);
      } catch (err) { toast(err.message); }
    } else if (ev.target.closest("[data-ep-more]")) {
      const open = row.classList.toggle("open");
      row.querySelector("[data-ep-more]").setAttribute("aria-expanded", String(open));
    }
  });
}

/** Keep an episode in Your Episodes (or take it out: its download goes too). */
async function saveEpisode(e, on) {
  await api.saveEpisode(e.episodeId, on);
  e.saved = on;
  if (!on && offline.isSaved(`episode:${e.episodeId}`)) await offline.remove(`episode:${e.episodeId}`);
  toast(on ? "Saved to Your Episodes" : "Removed from Your Episodes");
}

/** Download an episode to this device (it's kept in Your Episodes too), or delete the download. */
async function downloadEpisode(e) {
  const key = `episode:${e.episodeId}`;
  if (offline.isSaved(key)) {
    await offline.remove(key);
    toast("Removed from downloads");
    return;
  }
  if (!navigator.onLine) { toast("Connect to the internet to download"); return; }
  if (!e.saved) { await api.saveEpisode(e.episodeId, true); e.saved = true; }
  await offline.save("episode", e.episodeId, { ...e, saved: true });
  toast(`Downloading “${e.title}”`);
}

function setSaved(row, e) {
  const b = row.querySelector("[data-ep-save]");
  const label = e.saved ? "Remove from Your Episodes" : "Save to Your Episodes";
  b.setAttribute("aria-pressed", String(!!e.saved));
  b.setAttribute("aria-label", label);
  b.title = label;
  b.querySelector("use").setAttribute("href", e.saved ? "#i-saved" : "#i-save");
}

function showCard(s) {
  return `
    <div class="album-card pod-card">
      <div class="card-art"><a href="#/podcast/${s.id}" aria-label="${esc(s.title)}">${caseHtml({ id: s.albumId, cover: s.cover, title: s.title })}</a></div>
      <div class="card-title"><a href="#/podcast/${s.id}">${esc(s.title)}</a></div>
      <div class="card-sub">${s.unplayed ? `${plural(s.unplayed, "episode")} to hear` : "All heard"}</div>
    </div>`;
}

function resultRow(r, i) {
  return `
    <li class="pod-result">
      <span class="pod-result-art" aria-hidden="true">${r.image ? `<img src="${esc(r.image)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">` : ""}</span>
      <span class="pod-result-text"><b>${esc(r.title)}</b><span>${esc([r.author, r.episodes ? plural(r.episodes, "episode") : null].filter(Boolean).join(" · "))}</span></span>
      ${r.following ? `<a class="btn btn-small" href="#/podcast/${r.id}">Following</a>`
    : `<button class="btn btn-small btn-primary" type="button" data-follow="${i}">Follow</button>`}
    </li>`;
}

/** The Podcasts page: find shows, what to go on with, new episodes, and your shows. */
export async function podcastsView(el, player, { q = "" } = {}) {
  const data = await api.podcasts();
  const going = data.continue, fresh = data.new;
  el.innerHTML = `
    <div class="page podcasts-page">
      <header class="page-head"><div>
        <h1 class="page-title">Podcasts</h1>
        <p class="page-sub">Follow any show: search for it, or paste its link from Podbean, Apple Podcasts or anywhere else that has a feed.</p>
      </div></header>
      <form class="pod-search" role="search" autocomplete="off">
        <input name="q" type="search" placeholder="Search for a show, or paste its link" value="${esc(q)}" aria-label="Search for a show, or paste its link" spellcheck="false">
        <button class="btn btn-primary" type="submit">Find</button>
      </form>
      <div class="pod-results" hidden></div>
      ${going.length ? `<section class="artist-section"><h2 class="section-title">Continue listening</h2>
        <ul class="ep-list" id="pod-going">${going.map((e, i) => episodeRow(e, i, { withShow: true })).join("")}</ul></section>` : ""}
      ${fresh.length ? `<section class="artist-section"><h2 class="section-title">New episodes</h2>
        <ul class="ep-list" id="pod-new">${fresh.map((e, i) => episodeRow(e, i, { withShow: true })).join("")}</ul></section>` : ""}
      ${data.shows.length ? `<section class="artist-section"><h2 class="section-title">Your shows</h2>
        <div class="shelf">${data.shows.map(showCard).join("")}</div></section>`
    : `<div class="empty"><strong>No shows yet</strong>Search for one you like above. New episodes of the shows you follow show up here and on Home.</div>`}
    </div>`;

  const redraw = () => podcastsView(el, player);
  wireEpisodes(el.querySelector("#pod-going"), going, player, redraw);
  wireEpisodes(el.querySelector("#pod-new"), fresh, player, redraw);

  const form = el.querySelector(".pod-search");
  const out = el.querySelector(".pod-results");
  let results = [];
  const find = async () => {
    const text = form.elements.q.value.trim();
    if (text.length < 2) { out.hidden = true; return; }
    out.hidden = false;
    out.innerHTML = `<p class="pod-note">${/^(https?:\/\/|\S+\.\S+\/?$)/i.test(text) ? "Reading that link…" : "Searching…"}</p>`;
    try {
      const r = await api.podcastSearch(text);
      results = r.results;
      out.innerHTML = r.error ? `<p class="pod-note">${esc(r.error)}</p>`
        : results.length ? `<ul class="pod-result-list">${results.map(resultRow).join("")}</ul>`
          : `<p class="pod-note">No shows found for “${esc(text)}”. If you have its link, paste that instead.</p>`;
    } catch (err) { out.innerHTML = `<p class="pod-note">${esc(err.message)}</p>`; }
  };
  form.addEventListener("submit", (e) => { e.preventDefault(); find(); });
  out.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-follow]");
    if (!b) return;
    b.disabled = true;
    b.textContent = "Adding…";
    try {
      const show = await api.followPodcast(results[Number(b.dataset.follow)].feedUrl);
      toast(`Following ${show.title}`);
      location.hash = `#/podcast/${show.id}`;
    } catch (err) {
      toast(err.message);
      b.disabled = false;
      b.textContent = "Follow";
    }
  });
  if (q) find();
}

/** One show: about it, and its episodes, newest first. */
export async function podcastView(el, id, player, { unheard = false } = {}) {
  const s = await api.podcast(id);
  const episodes = unheard ? s.episodeList.filter((e) => !e.finished) : s.episodeList;
  const next = s.episodeList.find((e) => e.position > 0 && !e.finished) ?? s.episodeList.find((e) => !e.finished);
  const facts = [plural(s.episodes, "episode"), s.unplayed ? `${s.unplayed} to hear` : "all heard"].join(", ");
  el.innerHTML = `
    <div class="album-page podcast-page">
      <section class="album-hero">
        <div class="album-hero-inner">
          <a class="back-link" href="#/podcasts" data-action="back"><svg><use href="#i-back"/></svg>Back</a>
          ${caseHtml({ id: s.albumId, cover: s.cover, title: s.title }, { size: 640, lazy: false, sizes: "(max-width: 760px) 72vw, 280px" })}
          <div>
            <p class="pod-kicker">Podcast</p>
            <h1 class="album-title">${esc(s.title)}</h1>
            ${s.author ? `<span class="album-artist">${esc(s.author)}</span>` : ""}
            <p class="album-facts">${esc(facts)}${s.error ? `<br>The last check didn’t work: ${esc(s.error)}` : ""}</p>
            <div class="album-actions">
              ${next ? `<button class="btn btn-album" type="button" data-pod="play"><svg><use href="#i-play"/></svg>${next.position > 0 ? "Resume" : "Play latest"}</button>` : ""}
              <button class="btn follow-btn" type="button" data-pod="follow" aria-pressed="${s.following}">${s.following ? "Following" : "Follow"}</button>
              ${s.following ? `<button class="icon-btn" type="button" data-pod="refresh" aria-label="Check for new episodes" title="Check for new episodes"><svg><use href="#i-refresh"/></svg></button>` : ""}
              ${s.link ? `<a class="btn" href="${esc(s.link)}" target="_blank" rel="noopener">Website</a>` : ""}
            </div>
          </div>
        </div>
      </section>
      <div class="pod-body">
        ${s.description ? `<p class="pod-about">${esc(s.description)}</p>` : ""}
        <div class="chips" role="group" aria-label="Show">
          <button class="chip" type="button" data-pod="all" aria-pressed="${!unheard}">All</button>
          <button class="chip" type="button" data-pod="unheard" aria-pressed="${unheard}">Not played</button>
        </div>
        ${episodes.length ? `<ul class="ep-list" id="pod-episodes">${episodes.map((e, i) => episodeRow(e, i)).join("")}</ul>`
    : `<p class="pod-note">You’ve heard every episode.</p>`}
      </div>
    </div>`;

  const redraw = (opts = { unheard }) => podcastView(el, id, player, opts);
  wireEpisodes(el.querySelector("#pod-episodes"), episodes, player, () => redraw());
  el.querySelector(".podcast-page").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-pod]");
    if (!b) return;
    try {
      switch (b.dataset.pod) {
        case "play": player.playList([next], 0, { context: { label: s.title, href: `#/podcast/${s.id}` } }); break;
        case "all": redraw({ unheard: false }); break;
        case "unheard": redraw({ unheard: true }); break;
        case "refresh": {
          b.disabled = true;
          const r = await api.refreshPodcast(s.id);
          toast(r.new ? `${plural(r.new, "new episode")}` : "No new episodes yet");
          redraw();
          break;
        }
        case "follow":
          if (s.following) {
            await api.unfollowPodcast(s.id);
            toast(`Stopped following ${s.title}`);
            location.hash = "#/podcasts";
          } else {
            await api.followPodcast(s.feedUrl);
            redraw();
          }
          break;
      }
    } catch (err) { toast(err.message); }
  });
}

const EP_FILTERS = { unplayed: "Unplayed", downloaded: "Downloaded", going: "In progress" };
const EP_SORTS = { added: "Recently added", released: "Release date" };
let epSort = "added";
try { epSort = localStorage.getItem("epSort") || "added"; } catch { /* private window */ }

/** Your Episodes: the episodes you saved or downloaded, with filters, like a playlist of them. */
export async function yourEpisodesView(el, player, { filter = "", me = "" } = {}) {
  await offline.ready;
  const downloaded = offline.list().filter((c) => c.kind === "episode").map((c) => c.data);
  let all;
  let away = false;
  try {
    all = (await api.savedEpisodes()).episodes;
  } catch (err) {
    if (err.status !== 0) throw err;
    all = downloaded.map((e) => ({ ...e, savedAt: e.savedAt ?? 0 }));
    away = true;
  }
  // Downloads made here that the server doesn't list (taken out elsewhere) still show here.
  const known = new Set(all.map((e) => e.episodeId));
  for (const e of downloaded) if (!known.has(e.episodeId)) all.push(e);

  const pick = {
    unplayed: (e) => !e.finished,
    downloaded: (e) => offline.isSaved(`episode:${e.episodeId}`),
    going: (e) => e.position > 0 && !e.finished,
  }[filter] ?? (() => true);
  const shown = all.filter(pick).sort(epSort === "released"
    ? (a, b) => (b.published || 0) - (a.published || 0)
    : (a, b) => (b.savedAt || 0) - (a.savedAt || 0));

  el.innerHTML = `
    <div class="album-page your-episodes">
      <section class="album-hero">
        <div class="album-hero-inner">
          <a class="back-link" href="#/library" data-action="back"><svg><use href="#i-back"/></svg>Back</a>
          <span class="case yours-cover" aria-hidden="true"><svg><use href="#i-saved"/></svg></span>
          <div>
            <p class="pod-kicker">Playlist</p>
            <h1 class="album-title">Your Episodes</h1>
            <p class="album-facts">${esc([me, plural(all.length, "episode")].filter(Boolean).join(" • "))}${away ? "<br>You’re offline: these are the ones downloaded here." : ""}</p>
            <div class="album-actions">
              ${shown.some((e) => !e.finished) ? `<button class="btn btn-album" type="button" data-yours="play"><svg><use href="#i-play"/></svg>Play</button>` : ""}
              <label class="yours-sort"><span class="sr-only">Sort by</span>
                <select data-yours="sort">${Object.entries(EP_SORTS).map(([k, v]) => `<option value="${k}" ${k === epSort ? "selected" : ""}>${v}</option>`).join("")}</select></label>
            </div>
          </div>
        </div>
      </section>
      <div class="pod-body">
        <div class="chips" role="group" aria-label="Show">
          ${Object.entries(EP_FILTERS).map(([k, v]) => `<button class="chip" type="button" data-yours-filter="${k}" aria-pressed="${filter === k}">${v}</button>`).join("")}
        </div>
        ${shown.length ? `<ul class="ep-list" id="yours-list">${shown.map((e, i) => episodeRow(e, i, { withShow: true })).join("")}</ul>`
    : all.length ? `<p class="pod-note">Nothing here with that filter.</p>`
      : `<div class="empty"><strong>Nothing saved yet</strong>Save an episode with the bookmark next to it, or download it, and it shows up here.</div>`}
      </div>
    </div>`;

  const redraw = (f = filter) => yourEpisodesView(el, player, { filter: f, me });
  wireEpisodes(el.querySelector("#yours-list"), shown, player, () => redraw());
  el.querySelector(".your-episodes").addEventListener("click", (ev) => {
    const f = ev.target.closest("[data-yours-filter]");
    if (f) { redraw(f.dataset.yoursFilter === filter ? "" : f.dataset.yoursFilter); return; }
    if (ev.target.closest('[data-yours="play"]')) {
      const list = shown.filter((e) => !e.finished);
      player.playList(list, 0, { context: { label: "Your Episodes", href: "#/episodes" } });
    }
  });
  el.querySelector('[data-yours="sort"]').addEventListener("change", (ev) => {
    epSort = ev.target.value;
    try { localStorage.setItem("epSort", epSort); } catch { /* private window */ }
    redraw();
  });
}
