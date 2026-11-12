// Podcasts (see src/shelf/podcasts.py): follow shows by name or by pasting their link (Podbean,
// Apple Podcasts, a feed...), then play episodes in the ordinary player, which keeps your place.

import { api } from "./api.js";
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
      </div>
      <div class="ep-actions">
        <button class="icon-btn ep-done" type="button" data-ep-done aria-pressed="${e.finished}" title="${e.finished ? "Mark as not played" : "Mark as played"}"
          aria-label="${e.finished ? "Mark as not played" : "Mark as played"}"><svg><use href="#i-check"/></svg></button>
        <button class="ep-play" type="button" data-ep-play aria-label="Play ${esc(e.title)}" title="${e.position > 0 && !e.finished ? `Resume at ${fmtTime(e.position)}` : "Play"}"><svg><use href="#i-play"/></svg></button>
      </div>
    </li>`;
}

/** Play, mark and expand in a list of episodes. `redraw` after marking. */
export function wireEpisodes(list, episodes, player, redraw) {
  list?.addEventListener("click", async (ev) => {
    const row = ev.target.closest("[data-ep]");
    if (!row) return;
    const e = episodes[Number(row.dataset.ep)];
    if (ev.target.closest("[data-ep-play]")) {
      player.playList([e], 0, { context: { label: e.album, href: `#/podcast/${e.podcastId}` } });
    } else if (ev.target.closest("[data-ep-done]")) {
      try {
        await api.markEpisode(e.episodeId, !e.finished);
        redraw();
      } catch (err) { toast(err.message); }
    } else if (ev.target.closest("[data-ep-more]")) {
      const open = row.classList.toggle("open");
      row.querySelector("[data-ep-more]").setAttribute("aria-expanded", String(open));
    }
  });
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
