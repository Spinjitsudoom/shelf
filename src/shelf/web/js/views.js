// Each view renders into <main id="view"> and registers the track list it shows, so a
// click on any row can start playback from that list.

import { api } from "./api.js";
import { offline } from "./offline.js";
import { currentServer } from "./server.js";
import { detectDevice } from "./connect.js";
import { likeButton, likes } from "./likes.js";
import { STYLE_LABEL, describe as describeTransition, isCustom, normalize as normalizeTransition } from "./transitions.js";
import { EQ_BANDS, EQ_PRESETS, IS_IOS, QUALITY_LABELS, qualityDetail, settings } from "./settings.js";
import {
  applyAlbumColor, caseHtml, coverUrl, esc, fallbackColor, fmtAdded, fmtLength, fmtListening, fmtTime, keyBadge, playlistCover, plural, quality, store, toast,
} from "./util.js";

export const ctx = { tracks: [], context: null };
/** What's switched on for this server (set at sign-in): the DJ is experimental. */
export const features = { dj: false };

export const artistHref = (name) => `#/artist/${encodeURIComponent(name)}`;

/** A credit with each of its artists linked: "Aerosmith & Yungblud" is two links, one to
 *  each artist's page. `names` is the server's split of the credit. */
export function artistLinks(credit, names) {
  const list = names?.length ? names : [credit];
  const link = (n, text = n) => `<a href="${artistHref(n)}">${esc(text)}</a>`;
  if (list.length === 1) return link(list[0], credit || list[0]);
  const low = (credit || "").toLowerCase();
  let pos = 0, out = "";
  for (const n of list) {
    const i = low.indexOf(n.toLowerCase(), pos);
    if (i < 0) return list.map((x) => link(x)).join(", ");
    out += esc(credit.slice(pos, i)) + link(n, credit.slice(i, i + n.length));
    pos = i + n.length;
  }
  return out + esc(credit.slice(pos));
}

/** "Go to <artist>" menu items, one per artist of a credit. */
export const artistItems = (names) => names.map((n) => (
  { label: `Go to ${n}`, icon: "i-artists", run: () => { location.hash = artistHref(n); } }));

function setTracks(tracks, context) {
  ctx.tracks = tracks;
  ctx.context = context;
}

export function albumCard(a, { showArtist = true, sub: given } = {}) {
  const sub = given ? esc(given) : showArtist
    ? `${artistLinks(a.artist, a.artists)}${a.year ? `, ${a.year}` : ""}`
    : `${a.year ?? ""}${a.year ? ", " : ""}${plural(a.trackCount, "song")}`;
  return `
    <div class="album-card" data-album="${a.id}" data-artist="${esc(a.artist)}" data-artists="${esc(JSON.stringify(a.artists ?? [a.artist]))}">
      <div class="card-art">
        <a href="#/album/${a.id}" aria-label="${esc(a.title)} by ${esc(a.artist)}">${caseHtml(a)}</a>
        <button class="card-play" type="button" data-action="play-album" data-id="${a.id}" aria-label="Play ${esc(a.title)}">
          <svg><use href="#i-play"/></svg>
        </button>
      </div>
      <div class="card-title"><a href="#/album/${a.id}">${esc(a.title)}</a></div>
      <div class="card-sub">${sub}</div>
    </div>`;
}

function trackRow(t, i, { withArt = false } = {}) {
  const sub = withArt
    ? `${esc(t.artist)}, ${esc(t.album)}`
    : t.artist && t.albumArtist && t.artist.toLowerCase() !== t.albumArtist.toLowerCase() ? esc(t.artist) : "";
  return `
    <div class="track-row${withArt ? " with-art" : ""}" tabindex="0" data-index="${i}" data-track="${t.id}">
      ${withArt ? caseHtml(t, { size: 160, cls: "case-sm" }) : `<span class="num">${t.trackNo ?? i + 1}</span>`}
      <span class="t-main"><span class="t-title">${esc(t.title)}</span>${sub ? `<span class="t-sub">${sub}</span>` : ""}</span>
      <span class="row-actions">
        ${likeButton(t)}
        <button class="icon-btn desk" type="button" data-action="play-next" data-index="${i}" aria-label="Play next" title="Play next"><svg><use href="#i-next-up"/></svg></button>
        <button class="icon-btn desk" type="button" data-action="add-queue" data-index="${i}" aria-label="Add to queue" title="Add to queue"><svg><use href="#i-plus"/></svg></button>
        <button class="icon-btn" type="button" data-action="menu-track" data-index="${i}" aria-label="More options for ${esc(t.title)}" aria-haspopup="menu"><svg><use href="#i-more"/></svg></button>
      </span>
      <span class="dur">${fmtTime(t.duration)}</span>
    </div>`;
}

function rowShelf(title, albums, { href, showArtist = true } = {}) {
  if (!albums.length) return "";
  return `
    <section class="row-section">
      <div class="row-head">
        <h2 class="section-title">${esc(title)}</h2>
        ${href ? `<a class="see-all" href="${href}">See all</a>` : ""}
      </div>
      <div class="row-shelf">${albums.map((a) => albumCard(a, { showArtist })).join("")}</div>
    </section>`;
}

function ago(ts) {
  const days = Math.floor((Date.now() / 1000 - ts) / 86400);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 7) return `${days} days ago`;
  return new Date(ts * 1000).toLocaleDateString(undefined, { month: "long", day: "numeric" });
}

// ---------- home ----------

export async function homeView(el, player) {
  const [home, made, rel] = await Promise.all([api.home(), api.mixes().catch(() => []), api.releases().catch(() => null)]);
  const yearAgo = new Date(Date.now() - 365 * 86400_000).toISOString().slice(0, 10);
  const fresh = (rel?.releases ?? []).filter((r) => r.date >= yearAgo);
  setTracks([], null);
  if (!home.added.length) {
    el.innerHTML = `<div class="page"><header class="page-head"><h1 class="page-title">Home</h1></header>${emptyLibrary()}</div>`;
    return;
  }
  const cur = player.current;
  const last = home.recent[0];
  let hero;
  if (cur) {
    const t = player.position;
    const line = player.playing ? `Playing “${esc(cur.title)}”`
      : t > 1 ? `Paused at ${fmtTime(t)} in “${esc(cur.title)}”` : `Up now: “${esc(cur.title)}”`;
    hero = heroHtml({ id: cur.albumId, cover: cur.cover, title: cur.album }, artistLinks(cur.albumArtist || cur.artist, cur.albumArtists || cur.artists), line,
      `<button class="btn btn-album" type="button" data-action="toggle"><svg><use href="#${player.playing ? "i-pause" : "i-play"}"/></svg>${player.playing ? "Pause" : "Resume"}</button>`);
  } else if (last) {
    hero = heroHtml(last, artistLinks(last.artist, last.artists), `Last played ${ago(last.lastPlayed)}`,
      `<button class="btn btn-album" type="button" data-action="play-album" data-id="${last.id}"><svg><use href="#i-play"/></svg>Play</button>`);
  } else {
    hero = `
      <section class="hero hero-welcome">
        <div class="hero-stack" aria-hidden="true">${home.added.slice(0, 3).map((a) => caseHtml(a, { lazy: false, size: 320 })).join("")}</div>
        <div class="hero-text">
          <h2 class="hero-title">Put something on</h2>
          <p class="hero-line">Shuffle the whole shelf, or pick an album below. This page fills in with what you play.</p>
          <div class="album-actions"><button class="btn btn-primary" type="button" data-action="shuffle-all"><svg><use href="#i-shuffle"/></svg>Shuffle everything</button></div>
        </div>
      </section>`;
  }
  const week = home.week.plays
    ? `${plural(home.week.plays, "song")}, ${fmtListening(home.week.seconds)} of listening this week`
    : "Nothing played this week yet";
  const recent = cur ? home.recent : home.recent.slice(1);

  el.innerHTML = `
    <div class="page">
      <header class="page-head">
        <div><h1 class="page-title">Home</h1><p class="page-sub"><a class="home-stats" href="#/stats" title="Your listening">${week}</a></p></div>
      </header>
      ${hero}
      <section class="row-section">
        <div class="row-head"><h2 class="section-title">Made for you</h2></div>
        <div class="row-shelf">${features.dj ? djCard() : ""}${made.map(mixCard).join("")}</div>
      </section>
      ${fresh.length ? `<section class="row-section">
        <div class="row-head"><h2 class="section-title">New from your artists</h2><a class="see-all" href="#/releases">See all</a></div>
        <div class="row-shelf">${fresh.map(releaseCard).join("")}</div>
      </section>` : ""}
      ${rowShelf("Recently played", recent)}
      ${rowShelf("Recently added", home.added, { href: "#/albums?sort=added" })}
      ${rowShelf("Most played", home.top)}
      ${home.rediscover.length >= 4 ? rowShelf("Haven’t heard these in a while", home.rediscover) : ""}
    </div>`;
  const heroEl = el.querySelector(".hero:not(.hero-welcome)");
  if (heroEl && cur) api.album(cur.albumId).then((a) => applyAlbumColor(heroEl, a.color)).catch(() => {});
  else if (heroEl && last) applyAlbumColor(heroEl, last.color);
}

function heroHtml(album, artist, line, button) {
  return `
    <section class="hero">
      <a class="hero-art" href="#/album/${album.id}" aria-label="Open ${esc(album.title)}">${caseHtml(album, { size: 640, lazy: false, sizes: "(max-width: 760px) 40vw, 240px" })}</a>
      <div class="hero-text">
        <h2 class="hero-title"><a href="#/album/${album.id}">${esc(album.title)}</a></h2>
        <span class="hero-artist">${artist}</span>
        <p class="hero-line">${line}</p>
        <div class="album-actions">${button}<a class="btn" href="#/album/${album.id}">Open album</a></div>
      </div>
    </section>`;
}

// ---------- albums ----------

const SORTS = [
  ["artist", "Artist"],
  ["title", "Title"],
  ["year", "Year"],
  ["added", "Recently added"],
];

export async function albumsView(el, sortParam) {
  if (sortParam && SORTS.some(([k]) => k === sortParam)) store.set("albumSort", sortParam);
  const sort = store.get("albumSort", "artist");
  const albums = await api.albums(sort);
  setTracks([], null);
  if (!albums.length) {
    el.innerHTML = `<div class="page"><header class="page-head"><h1 class="page-title">Albums</h1></header>${emptyLibrary()}</div>`;
    return;
  }
  el.innerHTML = `
    <div class="page">
      <header class="page-head">
        <div>
          <h1 class="page-title">Albums</h1>
          <p class="page-sub">${plural(albums.length, "album")} on the shelf</p>
        </div>
        <div class="head-tools">
          <div class="segmented" role="group" aria-label="Sort albums by">
            ${SORTS.map(([k, label]) => `<button type="button" data-action="sort" data-sort="${k}" aria-pressed="${k === sort}">${label}</button>`).join("")}
          </div>
          <button class="btn" type="button" data-action="shuffle-all"><svg><use href="#i-shuffle"/></svg>Shuffle all</button>
        </div>
      </header>
      <div class="shelf">${albums.map((a) => albumCard(a)).join("")}</div>
    </div>`;
}

function emptyLibrary() {
  return `
    <div class="empty">
      <strong>Your shelf is empty</strong>
      <span class="admin-only">Add the folder where your music is in the
      <a href="#/admin" style="text-decoration:underline">admin dashboard</a>. New rips are picked up automatically every few minutes.</span>
      <span class="not-admin">Ask the person who runs this server to add the music folders.</span>
    </div>`;
}

// ---------- album ----------

export async function albumView(el, id) {
  const a = await api.album(id);
  setTracks(a.tracks, { label: a.title, href: `#/album/${a.id}` });
  const multiDisc = new Set(a.tracks.map((t) => t.discNo ?? 1)).size > 1;
  let lastDisc = null;
  const rows = a.tracks.map((t, i) => {
    let label = "";
    const d = t.discNo ?? 1;
    if (multiDisc && d !== lastDisc) {
      label = `<div class="disc-label">Disc ${d}</div>`;
      lastDisc = d;
    }
    return label + trackRow(t, i);
  }).join("");

  const q = quality(a.tracks);
  const facts = [a.year, plural(a.trackCount, "song"), fmtLength(a.duration)].filter(Boolean).join(", ");

  el.innerHTML = `
    <div class="album-page">
      <section class="album-hero">
        <div class="album-hero-inner">
          <a class="back-link" href="#/albums" data-action="back"><svg><use href="#i-back"/></svg>Back</a>
          ${caseHtml(a, { size: 640, lazy: false, sizes: "(max-width: 760px) 72vw, 280px" })}
          <div>
            <h1 class="album-title${titleFit(a.title)}">${esc(a.title)}</h1>
            <span class="album-artist">${artistLinks(a.artist, a.artists)}</span>
            <p class="album-facts">${esc(facts)}${a.genre ? `<br>${esc(a.genre)}` : ""}</p>
            ${q ? `<p class="album-quality"><span class="badge${q.lossless ? " lossless" : ""}">${esc(q.label)}</span><span>${esc(q.detail)}</span></p>` : ""}
            <div class="album-actions">
              <button class="btn btn-album" type="button" data-action="play-list"><svg><use href="#i-play"/></svg>Play</button>
              <button class="btn squeeze" type="button" data-action="shuffle-list"><svg><use href="#i-shuffle"/></svg><span class="btn-text">Shuffle</span></button>
              <button class="btn squeeze" type="button" data-action="add-all"><svg><use href="#i-plus"/></svg><span class="btn-text">Add to queue</span></button>
              ${downloadButton("album", a.id)}
            </div>
          </div>
        </div>
      </section>
      <div class="tracklist">
        <div class="track-head" aria-hidden="true"><span>#</span><span>Title</span><span></span><span><svg><use href="#i-clock"/></svg></span></div>
        ${rows}
      </div>
      <div class="album-more" id="album-more"></div>
    </div>`;
  applyAlbumColor(el, a.color);

  // More by this artist (each artist of a shared album), filled in without holding up the page.
  const names = a.artists?.length ? a.artists : [a.artist];
  Promise.all(names.map((n) => api.artistAlbums(n).catch(() => []))).then((lists) => {
    const slot = el.querySelector("#album-more");
    if (!slot) return;
    slot.innerHTML = names.map((n, i) => {
      const more = lists[i].filter((x) => x.id !== a.id);
      return more.length ? rowShelf(`More by ${n}`, more, { href: artistHref(n), showArtist: names.length > 1 }) : "";
    }).join("");
  });
}

// ---------- playlists ----------

function playlistRow(t, i) {
  return `
    <div class="track-row pl-row${t.entryId ? "" : " liked-row"}" tabindex="0" data-index="${i}" data-track="${t.id}"${t.entryId ? ` data-entry="${t.entryId}"` : ""}>
      <span class="num">${i + 1}</span>
      <span class="pl-main">${caseHtml(t, { size: 160, cls: "case-sm", sizes: "40px" })}
        <span class="t-main"><span class="t-title">${esc(t.title)}</span><span class="t-sub">${esc(t.artist)}${t.byLine ? `<span class="pl-by"> • ${esc(t.byLine)}</span>` : ""}</span></span></span>
      <span class="pl-bpm">${t.bpm ?? ""}</span>
      <span class="pl-key">${keyBadge(t)}</span>
      <a class="pl-album" href="#/album/${t.albumId}">${esc(t.album)}</a>
      <span class="pl-added">${fmtAdded(t.addedAt)}</span>
      <span class="row-actions">
        ${likeButton(t)}
        <button class="icon-btn" type="button" data-action="menu-track" data-index="${i}" aria-label="More options for ${esc(t.title)}" aria-haspopup="menu"><svg><use href="#i-more"/></svg></button>
      </span>
      <span class="dur">${fmtTime(t.duration)}</span>
    </div>`;
}

/** Mix: the pill under a song saying how it hands over to the next one. */
function transitionPill(t, nxt, i) {
  const setting = normalizeTransition(t.transition);
  const custom = isCustom(setting);
  return `
    <div class="mix-gap">
      <button class="mix-pill${setting.preset === "auto" && !custom ? "" : " set"}" type="button" data-action="pl-transition" data-index="${i}"
        title="${esc(describeTransition(t, nxt, setting))}. Select to edit."><svg><use href="#${custom ? "i-edit" : "i-mix"}"/></svg>${STYLE_LABEL[setting.preset]}</button>
    </div>`;
}

/** One playlist. `find` keeps the "add songs" search filled in across re-renders. */
export async function playlistView(el, id, { find = "" } = {}) {
  const p = await api.playlist(id);
  const tracks = p.tracks;
  setTracks(tracks, { label: p.name, href: `#/playlist/${p.id}`, mix: p.mix, playlistId: p.id, canEdit: p.canEdit, shared: p.shared });
  const facts = [
    p.mine ? "" : `By ${esc(p.owner.username)}`,
    tracks.length ? `${plural(tracks.length, "song")}, ${fmtLength(p.duration)}` : "No songs yet",
    p.mine && p.shared && p.followers ? plural(p.followers, "follower") : "",
  ].filter(Boolean).join(", ");
  const kind = p.shared === 2 ? "Collaborative playlist" : p.shared === 1 ? "Public playlist" : "Playlist";
  // On a collaborative playlist, who added each song.
  if (p.shared === 2) for (const t of tracks) t.byLine = t.addedBy ? `Added by ${t.addedBy}` : "";
  el.innerHTML = `
    <div class="album-page playlist-page" data-playlist="${p.id}">
      <section class="album-hero pl-hero">
        <div class="album-hero-inner">
          <a class="back-link" href="#/playlists" data-action="back"><svg><use href="#i-back"/></svg>Back</a>
          ${playlistCover(p, { size: 320, cls: "pl-cover-lg" })}
          <div>
            <p class="hero-kind">${p.shared ? `<svg class="kind-icon"><use href="#${p.shared === 2 ? "i-people" : "i-globe"}"/></svg>` : ""}${kind}</p>
            <h1 class="album-title${titleFit(p.name)}">${p.mine ? `<button class="pl-name" type="button" data-action="pl-edit" title="Edit details">${esc(p.name)}</button>` : esc(p.name)}</h1>
            ${p.description ? `<p class="pl-desc">${esc(p.description)}</p>` : ""}
            <p class="album-facts">${facts}</p>
            <div class="album-actions">
              ${tracks.length ? `
                <button class="btn btn-primary" type="button" data-action="play-list"><svg><use href="#i-play"/></svg>Play</button>
                <button class="btn squeeze" type="button" data-action="shuffle-list"><svg><use href="#i-shuffle"/></svg><span class="btn-text">Shuffle</span></button>` : ""}
              ${p.canEdit ? `<button class="btn squeeze" type="button" data-action="pl-addpanel"><svg><use href="#i-plus"/></svg><span class="btn-text">Add</span></button>` : ""}
              ${p.mine ? "" : `<button class="btn follow-btn" type="button" data-action="pl-follow" aria-pressed="${p.following}">${p.following ? "Following" : "Follow"}</button>`}
              ${tracks.length ? downloadButton("playlist", p.id) : ""}
              ${tracks.length > 1 && p.mine ? `<button class="btn squeeze mix-toggle" type="button" data-action="pl-mix" aria-pressed="${p.mix}"
                title="${p.mix ? "Mix is on: songs blend into each other like a DJ set" : "Play this playlist as a DJ-style mix"}"><svg><use href="#i-mix"/></svg><span class="btn-text">Mix</span></button>` : ""}
              ${p.mine ? `<button class="icon-btn" type="button" data-action="pl-menu" aria-label="More options for this playlist" aria-haspopup="menu"><svg><use href="#i-more"/></svg></button>` : ""}
            </div>
          </div>
        </div>
      </section>
      <div class="tracklist pl-tracks${tempoCls(tracks)}" data-playlist="${p.id}">
        ${tracks.length ? `
          <div class="track-head pl-head" aria-hidden="true"><span>#</span><span>Title</span><span class="pl-bpm">BPM</span><span class="pl-key">Key</span><span class="pl-album">Album</span><span class="pl-added">Date added</span><span></span><span><svg><use href="#i-clock"/></svg></span></div>
          ${tracks.map((t, i) => playlistRow(t, i) + (p.mix && i < tracks.length - 1 ? transitionPill(t, tracks[i + 1], i) : "")).join("")}` : ""}
      </div>
      ${tracks.length && p.canEdit ? `<div class="pl-findmore"><button class="text-btn" type="button" data-action="pl-findmore" aria-expanded="${find ? "true" : "false"}">Find more</button></div>` : ""}
      <section class="pl-find"${(tracks.length && !find) || !p.canEdit ? " hidden" : ""}>
        <h2 class="section-title">Let’s find something for your playlist</h2>
        <label class="search-box">
          <span class="sr-only">Search for songs to add</span>
          <svg><use href="#i-search"/></svg>
          <input id="pl-find" type="search" placeholder="Search for songs" value="${esc(find)}" autocomplete="off">
        </label>
        <div id="pl-find-results"></div>
      </section>
      ${tracks.length && p.canEdit ? `<section class="pl-recs" id="pl-recs" aria-labelledby="pl-recs-title">
        <h2 class="pl-recs-title" id="pl-recs-title">Recommended</h2>
        <p class="page-sub">Based on what’s in this playlist</p>
        <div id="pl-recs-list"><p class="page-sub">Finding songs…</p></div>
        <div class="pl-recs-foot"><button class="text-btn" type="button" data-action="pl-refresh">Refresh</button></div>
      </section>` : ""}
    </div>`;

  // Tint the header with the first album's color, as album pages are.
  if (p.covers[0]) api.album(p.covers[0].albumId).then((a) => { if (el.querySelector(`[data-playlist="${p.id}"]`)) applyAlbumColor(el, a.color); }).catch(() => {});
  const input = el.querySelector("#pl-find");
  const out = el.querySelector("#pl-find-results");
  let timer;
  const run = async () => {
    const q = input.value.trim();
    if (!q) { out.innerHTML = ""; return; }
    const r = await api.search(q);
    if (input.value.trim() !== q) return;
    out.innerHTML = r.tracks.length ? r.tracks.slice(0, 20).map((t) => `
      <div class="track-row with-art pl-add-row" data-track="${t.id}">
        ${caseHtml(t, { size: 160, cls: "case-sm" })}
        <span class="t-main"><span class="t-title">${esc(t.title)}</span><span class="t-sub">${esc(t.artist)}, ${esc(t.album)}</span></span>
        <span></span>
        <button class="btn btn-small" type="button" data-action="pl-add" data-track="${t.id}">Add</button>
      </div>`).join("") : `<p class="page-sub">No songs match “${esc(q)}”.</p>`;
  };
  input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => run().catch(() => {}), 180); });
  if (find) await run();
  if (tracks.length && p.canEdit) await drawRecommendations(el, p.id, recSeed);
  return p;
}

let recSeed = 0;
export const refreshRecommendations = (el, id) => drawRecommendations(el, id, ++recSeed);

async function drawRecommendations(el, id, seed) {
  const slot = el.querySelector("#pl-recs-list");
  if (!slot) return;
  const recs = await api.recommendations(id, seed).catch(() => []);
  if (!el.contains(slot)) return;
  slot.innerHTML = recs.length ? recs.map((t) => `
    <div class="track-row pl-row pl-rec" data-track="${t.id}">
      <span class="num"></span>
      <span class="pl-main">${caseHtml(t, { size: 160, cls: "case-sm", sizes: "40px" })}
        <span class="t-main"><span class="t-title">${esc(t.title)}</span><span class="t-sub">${esc(t.artist)}</span></span></span>
      <span class="pl-bpm">${t.bpm ?? ""}</span>
      <span class="pl-key">${keyBadge(t)}</span>
      <a class="pl-album" href="#/album/${t.albumId}">${esc(t.album)}</a>
      <span class="pl-added"></span>
      <span></span>
      <button class="btn btn-small" type="button" data-action="pl-add" data-track="${t.id}" data-suggested="1">Add</button>
    </div>`).join("") : `<p class="page-sub">Everything in your library that fits is already here.</p>`;
}

// ---------- liked songs ----------

export function likedCover(cls = "") {
  return `<span class="pl-cover liked-cover ${cls}"><svg><use href="#i-heart"/></svg></span>`;
}

export async function likedView(el) {
  const tracks = await api.likes();
  setTracks(tracks, { label: "Favourites", href: "#/liked" });
  const secs = tracks.reduce((n, t) => n + (t.duration || 0), 0);
  el.innerHTML = `
    <div class="album-page playlist-page liked-page">
      <section class="album-hero pl-hero">
        <div class="album-hero-inner">
          <a class="back-link" href="#/playlists" data-action="back"><svg><use href="#i-back"/></svg>Back</a>
          ${likedCover("pl-cover-lg")}
          <div>
            <p class="hero-kind">Playlist</p>
            <h1 class="album-title">Favourites</h1>
            <p class="album-facts">${tracks.length ? `${plural(tracks.length, "song")}, ${fmtLength(secs)}` : "No songs yet"}</p>
            ${tracks.length ? `<div class="album-actions">
              <button class="btn btn-primary" type="button" data-action="play-list"><svg><use href="#i-play"/></svg>Play</button>
              <button class="btn squeeze" type="button" data-action="shuffle-list"><svg><use href="#i-shuffle"/></svg><span class="btn-text">Shuffle</span></button>
              ${downloadButton("liked")}
            </div>` : ""}
          </div>
        </div>
      </section>
      <div class="tracklist pl-tracks${tempoCls(tracks)}">
        ${tracks.length ? `
          <div class="track-head pl-head" aria-hidden="true"><span>#</span><span>Title</span><span class="pl-bpm">BPM</span><span class="pl-key">Key</span><span class="pl-album">Album</span><span class="pl-added">Date added</span><span></span><span><svg><use href="#i-clock"/></svg></span></div>
          ${tracks.map(playlistRow).join("")}`
          : `<div class="empty"><strong>Songs you like will appear here</strong>Save songs by tapping the heart next to them.</div>`}
      </div>
    </div>`;
  applyAlbumColor(el, "#4a3ae0");
}

export async function playlistsView(el) {
  const list = await api.playlists();
  setTracks([], null);
  el.innerHTML = `
    <div class="page">
      <header class="page-head">
        <div>
          <h1 class="page-title">Playlists</h1>
          <p class="page-sub">${list.length ? plural(list.length, "playlist") : "Make a playlist to mix songs from any album."}</p>
        </div>
        <div class="head-tools"><button class="btn" type="button" data-action="pl-make"><svg><use href="#i-sparkle"/></svg>Make a playlist</button><button class="btn btn-primary" type="button" data-action="pl-new"><svg><use href="#i-plus"/></svg>New playlist</button></div>
      </header>
      ${list.length || likes.count ? `<div class="shelf">
        <a class="pl-card" href="#/liked">
          ${likedCover()}
          <span class="card-title">Favourites</span>
          <span class="card-sub">${plural(likes.count, "song")}</span>
        </a>${list.map((p) => `
        <a class="pl-card" href="#/playlist/${p.id}" data-playlist="${p.id}">
          ${playlistCover(p, { size: 320 })}
          <span class="card-title">${esc(p.name)}</span>
          <span class="card-sub">${plural(p.trackCount, "song")}</span>
        </a>`).join("")}</div>` : ""}
    </div>`;
}

// ---------- artists ----------

export async function artistsView(el) {
  const artists = await api.artists();
  setTracks([], null);
  if (!artists.length) {
    el.innerHTML = `<div class="page"><header class="page-head"><h1 class="page-title">Artists</h1></header>${emptyLibrary()}</div>`;
    return;
  }
  el.innerHTML = `
    <div class="page">
      <header class="page-head">
        <div>
          <h1 class="page-title">Artists</h1>
          <p class="page-sub">${plural(artists.length, "artist")}</p>
        </div>
      </header>
      <div class="artist-list">
        ${artists.map((ar) => `
          <a class="artist-row" href="${artistHref(ar.name)}">
            ${caseHtml({ id: ar.coverAlbumId, cover: ar.cover, title: ar.name }, { size: 160, sizes: "64px" })}
            <span><span class="artist-name">${esc(ar.name)}</span><br>
            <span class="artist-count">${plural(ar.albums, "album")}, ${plural(ar.tracks, "song")}</span></span>
          </a>`).join("")}
      </div>
    </div>`;
}

const KIND_LABEL = { album: "Album", ep: "EP", single: "Single", compilation: "Compilation" };
const DISCOGRAPHY = [
  ["popular", "Popular releases", () => true],
  ["album", "Albums", (a) => a.kind === "album"],
  ["single", "Singles and EPs", (a) => a.kind === "single" || a.kind === "ep"],
  ["compilation", "Compilations", (a) => a.kind === "compilation"],
];
const POPULAR_SHOWN = 5;

function popularRow(t, i) {
  return `
    <div class="track-row pop-row" tabindex="0" data-index="${i}" data-track="${t.id}"${i >= POPULAR_SHOWN ? " data-extra" : ""}>
      <span class="num">${i + 1}</span>
      <span class="pl-main">${caseHtml(t, { size: 160, cls: "case-sm", sizes: "40px" })}
        <span class="t-main"><span class="t-title">${esc(t.title)}</span>${t.albumArtist && t.artist.toLowerCase() !== t.albumArtist.toLowerCase() ? `<span class="t-sub">${esc(t.artist)}</span>` : ""}</span></span>
      <span class="pop-plays">${t.plays ? plural(t.plays, "play") : ""}</span>
      <span class="row-actions">
        ${likeButton(t)}
        <button class="icon-btn desk" type="button" data-action="add-queue" data-index="${i}" aria-label="Add to queue" title="Add to queue"><svg><use href="#i-plus"/></svg></button>
        <button class="icon-btn" type="button" data-action="menu-track" data-index="${i}" aria-label="More options for ${esc(t.title)}" aria-haspopup="menu"><svg><use href="#i-more"/></svg></button>
      </span>
      <span class="dur">${fmtTime(t.duration)}</span>
    </div>`;
}

const releaseSub = (a) => [a.year, KIND_LABEL[a.kind] ?? "Album"].filter(Boolean).join(", ");

function drawDiscography(slot, albums, which, all) {
  const [, , keep] = DISCOGRAPHY.find(([k]) => k === which) ?? DISCOGRAPHY[0];
  let list = albums.filter(keep);
  if (which === "popular") list = [...list].sort((a, b) => (b.plays - a.plays) || ((b.year ?? 0) - (a.year ?? 0)));
  slot.className = all ? "shelf" : "row-shelf";
  slot.innerHTML = list.map((a) => albumCard(a, { sub: releaseSub(a) })).join("");
}

/** Videos whose owners only allowed them on YouTube itself (see main.js), noted for 30 days. */
const YT_ONLY_DAYS = 30;
export const youTubeOnlyList = () =>
  store.get("ytOnly", []).filter((x) => Array.isArray(x) && Date.now() - x[1] < YT_ONLY_DAYS * 86_400_000);
export const youTubeOnly = () => new Set(youTubeOnlyList().map(([id]) => id));

export function videoCard(v) {
  const external = youTubeOnly().has(v.videoId);
  const inner = `
    <span class="vthumb"><img src="https://i.ytimg.com/vi/${encodeURIComponent(v.videoId)}/mqdefault.jpg" alt="" loading="lazy">
      <span class="vplay"><svg><use href="#${external ? "i-video" : "i-play"}"/></svg></span></span>
    <span class="card-title">${esc(v.title)}</span>
    <span class="card-sub">${external ? "Plays on YouTube" : v.duration ? fmtTime(v.duration) : esc(v.artist)}</span>`;
  return external
    ? `<a class="vcard" href="https://www.youtube.com/watch?v=${encodeURIComponent(v.videoId)}" target="_blank" rel="noopener" data-video="${esc(v.videoId)}" data-title="${esc(v.title)}">${inner}</a>`
    : `<button class="vcard" type="button" data-action="play-video" data-video="${esc(v.videoId)}" data-title="${esc(v.title)}" data-duration="${v.duration ?? ""}">${inner}</button>`;
}

export async function artistView(el, name) {
  const aboutP = api.artistAbout(name).catch(() => ({ found: false }));
  const data = await api.artist(name);
  // Wait a moment for the photo so the page usually draws once; it fades in if it's slower.
  const early = await Promise.race([aboutP, new Promise((r) => setTimeout(() => r(null), 350))]);
  const { stats, albums, popular } = data;
  const display = data.name;
  setTracks(popular, { label: display, href: artistHref(display) });

  const facts = [plural(stats.albums, albums.length && albums.every((a) => a.kind === "album") ? "album" : "release"),
    plural(stats.songs, "song"), stats.duration ? fmtLength(stats.duration) : null].filter(Boolean).join(", ");
  const listened = stats.plays ? `Their songs have been played ${plural(stats.plays, "time")}` : "Nobody has played their songs yet";
  const chips = DISCOGRAPHY.filter(([k, , keep]) => k === "popular" || albums.some(keep));
  const latest = albums[0];
  const topAlbum = [...albums].sort((a, b) => b.plays - a.plays)[0];

  el.innerHTML = `
    <div class="album-page artist-page">
      <header class="artist-hero" id="artist-hero">
        <div class="artist-hero-photo" aria-hidden="true"></div>
        <div class="artist-hero-text">
          <a class="back-link" href="#/artists" data-action="back"><svg><use href="#i-back"/></svg>Back</a>
          <h1 class="artist-title">${esc(display)}</h1>
          <p class="artist-facts">${esc(facts)}<span class="artist-listened">${esc(listened)}</span></p>
        </div>
      </header>
      <div class="artist-body">
        <div class="album-actions artist-actions">
          <button class="big-play" type="button" data-action="play-list" aria-label="Play ${esc(display)}" title="Play"${popular.length ? "" : " disabled"}><svg><use href="#i-play"/></svg></button>
          <button class="icon-btn artist-shuffle" type="button" data-action="shuffle-artist" data-artist="${esc(display)}" aria-label="Shuffle ${esc(display)}" title="Shuffle"><svg><use href="#i-shuffle"/></svg></button>
          <button class="btn" type="button" data-action="artist-radio" data-artist="${esc(display)}"><svg><use href="#i-radio"/></svg>Artist radio</button>
        </div>

        ${popular.length ? `<section class="artist-section">
          <h2 class="section-title">Popular</h2>
          <div class="pop-list" id="pop-list">${popular.map(popularRow).join("")}</div>
          ${popular.length > POPULAR_SHOWN ? `<button class="see-more" type="button" id="pop-more" aria-expanded="false">See more</button>` : ""}
        </section>` : ""}

        ${albums.length ? `<div class="artist-pair">
          ${topAlbum?.plays ? `<section class="artist-section">
            <h2 class="section-title">Your listening</h2>
            <a class="pair-card" href="#/album/${topAlbum.id}">
              <span class="pair-art round">${caseHtml(topAlbum, { size: 320, sizes: "96px" })}</span>
              <span class="pair-text"><b>${plural(stats.songsPlayed, "song")} played</b>
                <span>Most played: ${esc(topAlbum.title)}</span>
                ${stats.lastPlayed ? `<span>Last played ${ago(stats.lastPlayed)}</span>` : ""}</span>
            </a>
          </section>` : ""}
          <section class="artist-section">
            <h2 class="section-title">Latest release</h2>
            <a class="pair-card" href="#/album/${latest.id}">
              <span class="pair-art">${caseHtml(latest, { size: 320, sizes: "96px" })}</span>
              <span class="pair-text"><b>${esc(latest.title)}</b><span>${esc(releaseSub(latest))}</span><span>${plural(latest.trackCount, "song")}, ${fmtLength(latest.duration)}</span></span>
            </a>
          </section>
        </div>

        <section class="artist-section">
          <div class="row-head">
            <h2 class="section-title">Discography</h2>
            ${albums.length > 5 ? `<button class="see-all" type="button" id="disco-all" aria-expanded="false">Show all</button>` : ""}
          </div>
          ${chips.length > 2 ? `<div class="chips disco-chips" role="group" aria-label="Show">${chips.map(([k, label], i) =>
            `<button class="chip" type="button" data-disco="${k}" aria-pressed="${i === 0}">${label}</button>`).join("")}</div>` : ""}
          <div id="disco"></div>
        </section>` : ""}

        <section class="artist-section" id="artist-videos" hidden></section>

        ${data.playlists.length ? `<section class="artist-section">
          <h2 class="section-title">Featuring ${esc(display)}</h2>
          <div class="row-shelf">${data.playlists.map((p) => `
            <a class="pl-card" href="#/playlist/${p.id}" data-playlist="${p.id}">
              ${playlistCover(p, { size: 320 })}
              <span class="card-title">${esc(p.name)}</span>
              <span class="card-sub">${plural(p.artistCount, "song")} by ${esc(display)}</span>
            </a>`).join("")}</div>
        </section>` : ""}

        ${data.appearsOn.length ? `<section class="artist-section">
          <h2 class="section-title">Appears on</h2>
          <div class="row-shelf">${data.appearsOn.map((a) => albumCard(a)).join("")}</div>
        </section>` : ""}

        <section class="artist-section" id="artist-missing" hidden></section>

        <section class="artist-section" id="artist-about" hidden></section>
      </div>
    </div>`;

  // Not on your shelf: this artist's other albums and EPs (from MusicBrainz), when known.
  api.releases().then((r) => {
    const mine = r.releases.filter((x) => x.artist.toLowerCase() === display.toLowerCase());
    const slot = el.querySelector("#artist-missing");
    if (!slot || !mine.length) return;
    slot.hidden = false;
    slot.innerHTML = `<div class="row-head"><h2 class="section-title">Not on your shelf</h2><a class="see-all" href="#/releases">See all</a></div>
      <div class="row-shelf">${mine.map(releaseCard).join("")}</div>`;
  }).catch(() => {});

  const hero = el.querySelector("#artist-hero");
  applyAlbumColor(el, topAlbum?.color ?? latest?.color);

  // Popular: five songs, "See more" shows ten.
  el.querySelector("#pop-more")?.addEventListener("click", (e) => {
    const open = el.querySelector("#pop-list").classList.toggle("open");
    e.currentTarget.textContent = open ? "Show less" : "See more";
    e.currentTarget.setAttribute("aria-expanded", String(open));
  });

  // Discography: one row, or all of it; the chips filter by kind of release.
  const disco = el.querySelector("#disco");
  if (disco) {
    let which = "popular";
    let all = false;
    const draw = () => drawDiscography(disco, albums, which, all);
    draw();
    el.querySelector(".disco-chips")?.addEventListener("click", (e) => {
      const chip = e.target.closest("[data-disco]");
      if (!chip) return;
      which = chip.dataset.disco;
      el.querySelectorAll("[data-disco]").forEach((c) => c.setAttribute("aria-pressed", String(c === chip)));
      draw();
    });
    el.querySelector("#disco-all")?.addEventListener("click", (e) => {
      all = !all;
      e.currentTarget.textContent = all ? "Show less" : "Show all";
      e.currentTarget.setAttribute("aria-expanded", String(all));
      draw();
    });
  }

  // The photo, the page's color and the About card, from Wikipedia.
  const showAbout = (a) => {
    if (!a?.found || !el.contains(hero)) return;
    if (a.image) {
      hero.classList.add("has-photo");
      hero.querySelector(".artist-hero-photo").style.backgroundImage = `url('${a.image}')`;
      if (a.color) applyAlbumColor(el, a.color);
    }
    const slot = el.querySelector("#artist-about");
    slot.hidden = false;
    slot.innerHTML = `
      <h2 class="section-title">About</h2>
      <a class="about-card${a.image ? " has-photo" : ""}" href="${esc(a.url ?? "#")}" target="_blank" rel="noopener">
        ${a.image ? `<span class="about-photo" style="background-image:url('${esc(a.image)}')"></span>` : ""}
        <span class="about-text">
          ${a.description ? `<b class="about-desc">${esc(a.description)}</b>` : ""}
          <span class="about-bio">${esc(a.extract)}</span>
          <span class="about-more">Read more on Wikipedia</span>
        </span>
      </a>`;
  };
  if (early) showAbout(early);
  else aboutP.then(showAbout);

  // The artist's music videos on YouTube.
  api.artistVideos(display).then((list) => {
    const slot = el.querySelector("#artist-videos");
    if (!slot || !list.length) return;
    slot.hidden = false;
    slot.innerHTML = `
      <h2 class="section-title">Music videos</h2>
      <div class="video-slot video-host" id="artist-video" hidden></div>
      <div class="row-shelf video-shelf">${list.map(videoCard).join("")}</div>`;
  }).catch(() => {});
}

// ---------- search ----------

let searchTimer;
export async function searchView(el, query) {
  setTracks([], null);
  el.innerHTML = `
    <div class="page">
      <header class="page-head"><h1 class="page-title">Search</h1></header>
      <label class="search-box">
        <span class="sr-only">Search your library</span>
        <svg><use href="#i-search"/></svg>
        <input id="search-input" type="search" placeholder="Artists, albums, songs" value="${esc(query)}" autocomplete="off" enterkeyhint="search">
      </label>
      <div id="search-results"></div>
    </div>`;
  const input = el.querySelector("#search-input");
  const results = el.querySelector("#search-results");
  const run = async () => {
    const q = input.value.trim();
    history.replaceState(null, "", q ? `#/search?q=${encodeURIComponent(q)}` : "#/search");
    if (!q) {
      results.innerHTML = "";
      setTracks([], null);
      return;
    }
    const r = await api.search(q);
    if (input.value.trim() !== q) return; // a newer query is on its way
    setTracks(r.tracks, { label: `Search: ${q}`, href: `#/search?q=${encodeURIComponent(q)}` });
    if (!r.artists.length && !r.albums.length && !r.tracks.length) {
      results.innerHTML = `<div class="empty"><strong>Nothing matches “${esc(q)}”</strong>Try part of a title or an artist’s name.</div>`;
      return;
    }
    results.innerHTML = `
      ${r.artists.length ? `<h2 class="section-title">Artists</h2><div class="artist-list">${r.artists.map((ar) => `
        <a class="artist-row" href="${artistHref(ar.name)}"><span><span class="artist-name">${esc(ar.name)}</span><br>
        <span class="artist-count">${plural(ar.albums, "album")}</span></span></a>`).join("")}</div>` : ""}
      ${r.albums.length ? `<h2 class="section-title">Albums</h2><div class="shelf">${r.albums.map((a) => albumCard(a)).join("")}</div>` : ""}
      ${r.tracks.length ? `<h2 class="section-title">Songs</h2><div>${r.tracks.map((t, i) => trackRow(t, i, { withArt: true })).join("")}</div>` : ""}`;
  };
  input.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => run().catch((e) => toast(e.message)), 180);
  });
  if (query) await run();
  if (!matchMedia("(max-width: 760px)").matches || !query) input.focus({ preventScroll: true });
}

// ---------- queue ----------

export function queueView(el, player) {
  const cur = player.current;
  const next = player.upNext;
  setTracks([], null); // queue rows map to queue positions, not a fresh list
  if (!cur) {
    el.innerHTML = `
      <div class="page">
        <header class="page-head"><h1 class="page-title">Queue</h1></header>
        <div class="empty"><strong>Nothing queued</strong>Play an album or song and it shows up here, along with whatever comes next.</div>
      </div>`;
    return;
  }
  const offset = player.index + 1;
  const left = next.reduce((n, t) => n + (t.duration || 0), 0);
  const qrow = (t, qi, actions) => `
    <div class="track-row with-art${qi === player.index ? ` playing${player.playing ? "" : " paused"}` : ""}" data-queue-index="${qi}" data-track="${t.id}" tabindex="0">
      ${caseHtml(t, { size: 160, cls: "case-sm" })}
      <span class="t-main"><span class="t-title">${t.smart ? `<svg class="smart-mark" aria-label="Smart shuffle suggestion"><use href="#i-sparkle"/></svg>` : ""}${esc(t.title)}</span><span class="t-sub">${esc(t.artist)}, ${esc(t.album)}</span></span>
      <span class="row-actions always">${t.smart && qi > player.index ? `<button class="icon-btn" type="button" data-action="keep-smart" data-queue-index="${qi}" aria-label="Keep ${esc(t.title)} in the queue" title="Keep it"><svg><use href="#i-check"/></svg></button>` : ""}${actions}</span>
      <span class="dur">${fmtTime(t.duration)}</span>
    </div>`;
  el.innerHTML = `
    <div class="page">
      <header class="page-head">
        <div>
          <h1 class="page-title">Queue</h1>
          ${player.context ? `<p class="page-sub">Playing from <a href="${esc(player.context.href)}" style="text-decoration:underline">${esc(player.context.label)}</a></p>` : ""}
        </div>
        ${next.length ? `<div class="head-tools"><button class="btn" type="button" data-action="clear-queue">Clear up next</button></div>` : ""}
      </header>
      <h2 class="section-title" style="margin-top:0">Now playing</h2>
      ${qrow(cur, player.index, "")}
      <h2 class="section-title">Up next${next.length ? `, ${plural(next.length, "song")}, ${fmtLength(left)}` : ""}</h2>
      ${next.length ? next.map((t, i) => (t.autoplay && !next[i - 1]?.autoplay ? `<h2 class="section-title">Autoplay: similar songs from your library</h2>` : "") + qrow(t, offset + i, `
          <button class="icon-btn" type="button" data-action="remove-queue" data-queue-index="${offset + i}" aria-label="Remove ${esc(t.title)} from the queue"><svg><use href="#i-close"/></svg></button>`)).join("")
        : `<p class="page-sub">That’s the last song${player.repeat === "all" ? ". Repeat is on, so the queue starts over after it." : "."}</p>`}
    </div>`;
}

// ---------- settings ----------

const sw = (key, label) =>
  `<button class="switch" type="button" role="switch" data-setting="${key}" aria-checked="${!!settings.get(key)}" aria-label="${esc(label)}"></button>`;

const select = (key, options, label) => `
  <select class="select" data-setting="${key}" aria-label="${esc(label)}">
    ${options.map(([v, text]) => `<option value="${v}"${settings.get(key) === v ? " selected" : ""}>${esc(text)}</option>`).join("")}
  </select>`;

const seg = (key, options, label, value = settings.get(key)) => `
  <div class="segmented" role="group" aria-label="${esc(label)}">
    ${options.map(([v, text]) => `<button type="button" data-setting="${key}" data-value="${v}" aria-pressed="${v === value}">${esc(text)}</button>`).join("")}
  </div>`;

export const row = (title, desc, control, attrs = "") => `
  <div class="setting" ${attrs}>
    <div><h3>${title}</h3>${desc ? `<p>${desc}</p>` : ""}</div>
    <div class="setting-control">${control}</div>
  </div>`;

export const fmtBytes = (n) => n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : n >= 1e6 ? `${Math.round(n / 1e6)} MB` : `${Math.round(n / 1e3)} KB`;
export const crossfadeLabel = (s) => (s > 0 ? `${s} s` : "Off");
export const balanceLabel = (b) => Math.abs(b) < 0.025 ? "Center" : `${b < 0 ? "Left" : "Right"} ${Math.round(Math.abs(b) * 100)}`;

export function eqSummary() {
  if (!settings.get("eqEnabled")) return "Off";
  return settings.get("eqPreset") === "Custom" ? "Custom" : settings.get("eqPreset");
}

const IOS_NOTE = `<p class="note">On iPhone and iPad, volume normalization, crossfade, mono, balance and the mixer send
  music through the browser’s sound processing. If music stops when your screen locks, turn these off.</p>`;

export async function settingsView(el, player, { user, version }) {
  const lib = await api.library();
  setTracks([], null);
  const theme = store.get("theme", "system");
  const measuring = lib.loudnessMeasured < lib.tracks
    ? `<br>Measuring song loudness: ${lib.loudnessMeasured} of ${lib.tracks} done. Songs not measured yet play at their usual volume.` : "";
  const server = currentServer().replace(/^https?:\/\//, "");
  const qualityOptions = Object.entries(QUALITY_LABELS);
  const cf = settings.get("crossfade");

  el.innerHTML = `
    <div class="page settings">
      <header class="page-head"><h1 class="page-title">Settings</h1></header>
      <div class="stats">
        <div class="stat"><b>${lib.albums}</b><span>albums</span></div>
        <div class="stat"><b>${lib.artists}</b><span>artists</span></div>
        <div class="stat"><b>${lib.tracks}</b><span>songs</span></div>
        <div class="stat"><b>${Math.round(lib.duration / 3600)}</b><span>hours of music</span></div>
      </div>
      <h2 class="settings-section">Account</h2>
      ${row(`Signed in as ${esc(user?.username ?? "")}${user?.admin ? ` <span class="tag">Admin</span>` : ""}`,
        "Your Favourites, playlists and listening history are your own. Other people on this server have theirs.",
        `<button class="btn" type="button" data-action="change-password"><svg><use href="#i-key"/></svg>Change password</button>`)}
      ${row("Share what I listen to", "People on this server see what you’re playing in Friend activity, and can make a Blend with you. Private sessions are never shown.",
        `<button class="switch" type="button" role="switch" data-action="share-activity" aria-checked="${user?.shareActivity !== false}" aria-label="Share what I listen to"></button>`)}
      ${row("ListenBrainz", user?.listenbrainz
        ? `Your listens go to ListenBrainz as <b>${esc(user.listenbrainz)}</b>.`
        : "Keep a record of everything you play on listenbrainz.org, the open alternative to Last.fm. Sends the artist, title and album of each song you play.",
        user?.listenbrainz
          ? `<button class="btn" type="button" data-action="lb-disconnect">Disconnect</button>`
          : `<button class="btn" type="button" data-action="lb-connect">Connect</button>`)}
      ${row("Last.fm", user?.lastfm
        ? `Your listens go to Last.fm as <b>${esc(user.lastfm)}</b>.`
        : user?.lastfmAvailable
          ? "Scrobble everything you play to your Last.fm profile. Sends the artist, title and album of each song you play."
          : user?.admin ? "To scrobble to Last.fm, first add a Last.fm API account in the admin dashboard." : "An admin can set up Last.fm on this server, then you can scrobble to it.",
        user?.lastfm
          ? `<button class="btn" type="button" data-action="lfm-disconnect">Disconnect</button>`
          : user?.lastfmAvailable ? `<button class="btn" type="button" data-action="lfm-connect">Connect</button>` : "")}
      ${row("Other music apps", user?.subsonic
        ? "Apps made for Subsonic, like Symfonium, Feishin and Substreamer, can play from Shelf with your app password."
        : "Play your music here from apps made for Subsonic, like Symfonium, Feishin, Substreamer and DSub. Setting up makes an app password to sign in to them with.",
        user?.subsonic
          ? `<button class="btn btn-small" type="button" data-action="subsonic-off">Turn off</button>
             <button class="btn" type="button" data-action="subsonic-show">Show details</button>`
          : `<button class="btn" type="button" data-action="subsonic-on">Set up</button>`)}
      ${row("Server", `Connected to <b>${esc(server)}</b>.`, `<button class="btn" type="button" data-action="change-server">Change server</button>`)}
      ${user?.admin ? row("Admin dashboard", "Add people, manage music folders, rescan the library and see how the server is doing.",
        `<a class="btn" href="#/admin"><svg><use href="#i-admin"/></svg>Open dashboard</a>`) : ""}
      ${row("Sign out", "Signs you out on this device only.", `<button class="btn" type="button" data-action="logout">Sign out</button>`)}

      <p class="settings-scope">Everything below applies to this device only.</p>

      <h2 class="settings-section">Audio quality</h2>
      ${row("Wi-Fi streaming", `<span data-detail="wifiQuality">${qualityDetail("wifiQuality", settings.get("wifiQuality"))}</span>`, select("wifiQuality", qualityOptions, "Wi-Fi streaming quality"))}
      ${row("Mobile data streaming", `<span data-detail="cellularQuality">${qualityDetail("cellularQuality", settings.get("cellularQuality"))}</span>. Used when your device reports it’s on mobile data; iPhones don’t, so they use the Wi-Fi setting.`, select("cellularQuality", qualityOptions, "Mobile data streaming quality"))}
      ${row("Auto-adjust quality", "Steps the quality down if the connection can’t keep up, so music doesn’t stop to buffer.", sw("autoAdjust", "Auto-adjust quality"))}

      <h2 class="settings-section">Playback</h2>
      ${row("Gapless playback", "Starts the next song with no break, so live albums and songs that run together sound as they should.", sw("gapless", "Gapless playback"))}
      ${row("Crossfade", "Fades each song into the next.", `
        <div class="range-row"><input type="range" class="range" min="0" max="12" step="1" value="${cf}" data-setting="crossfade" aria-label="Crossfade length"><output data-out="crossfade">${crossfadeLabel(cf)}</output></div>`)}
      ${row("Crossfade within albums", "Off keeps albums played in order seamless, the way they were mastered.", sw("crossfadeAlbums", "Crossfade within albums"), 'data-requires="crossfade"')}
      ${row("Autoplay", "When your queue ends, keep playing similar songs from your library.", sw("autoplay", "Autoplay"))}
      ${row("Mono audio", "Plays the left and right channels through both speakers.", sw("mono", "Mono audio"))}

      <h2 class="settings-section">Sound</h2>
      ${row("Volume normalization", `Plays every song at the same loudness. Albums played in order keep their own dynamics.${measuring}`, sw("normalize", "Volume normalization"))}
      ${row("Volume level", "Loud can slightly reduce dynamics in quiet songs.", seg("loudness", [["loud", "Loud"], ["normal", "Normal"], ["quiet", "Quiet"]], "Volume level"), 'data-requires="normalize"')}
      ${row("Mixer", `Equalizer and balance. <span data-detail="eq">Equalizer: ${esc(eqSummary())}</span>`, `<a class="btn" href="#/mixer"><svg><use href="#i-eq"/></svg>Open mixer</a>`)}
      ${IS_IOS ? IOS_NOTE : ""}

      <h2 class="settings-section">This device</h2>
      ${row("Device name", "How this device appears when you pick where to play from another one.",
        `<input type="text" class="text-input" data-setting="deviceName" maxlength="60" value="${esc(settings.get("deviceName") || "")}" placeholder="${esc(detectDevice().name)}" aria-label="Device name">`)}

      <h2 class="settings-section">Display</h2>
      ${row("Appearance", "Follow your device, or always use light or dark.", seg("theme", [["system", "Device"], ["light", "Light"], ["dark", "Dark"]], "Appearance", theme))}
      ${row("Format", "Your shelf as CDs in jewel cases, or as records in their sleeves.",
        seg("shelfFormat", [["cd", "CD"], ["vinyl", "Vinyl"]], "Format"))}
      ${row("Spinning disc", "The CD (or record) turns on Now Playing while music plays.", sw("spinDisc", "Spinning disc"))}

      <h2 class="settings-section">Privacy</h2>
      ${row("Private session", "Songs you play on this device aren’t added to your listening history or Home.", sw("privateSession", "Private session"))}
      ${row("Listening history", "Clears your Recently played and Most played, on all your devices.", `<button class="btn" type="button" data-action="clear-history">Clear history</button>`)}

      <h2 class="settings-section">Downloads</h2>
      ${row("Download quality", "For new downloads. Very high sounds like the original to most ears at a fraction of the size.",
        select("downloadQuality", qualityOptions.filter(([k]) => k !== "auto"), "Download quality"))}
      ${row("On this device", `<span data-detail="downloads">${plural(offline.count(), "song")} downloaded.</span>`,
        `<a class="btn" href="#/downloads"><svg><use href="#i-download"/></svg>See downloads</a>
         <button class="btn" type="button" data-action="downloads-clear" ${offline.list().length ? "" : "disabled"}>Remove all</button>`)}

      <h2 class="settings-section">Keyboard shortcuts</h2>
      <dl class="shortcuts">
        <div><dt><kbd>Space</kbd></dt><dd>Play or pause</dd></div>
        <div><dt><kbd>←</kbd> <kbd>→</kbd></dt><dd>Back or forward 10 seconds</dd></div>
        <div><dt><kbd>Shift</kbd> + <kbd>←</kbd> <kbd>→</kbd></dt><dd>Previous or next song</dd></div>
        <div><dt><kbd>/</kbd></dt><dd>Search</dd></div>
        <div><dt><kbd>Esc</kbd></dt><dd>Close Now Playing or a menu</dd></div>
      </dl>

      <p class="about">Shelf ${esc(version ?? "")}</p>
    </div>`;
  refreshSettings(el);
}

/** Bring switches, outputs and dependent rows in line with current settings, without a re-render. */
export function refreshSettings(el) {
  el.querySelectorAll('.switch[data-setting]').forEach((b) => b.setAttribute("aria-checked", String(!!settings.get(b.dataset.setting))));
  el.querySelectorAll('[data-setting][data-value]').forEach((b) => {
    if (b.dataset.setting !== "theme") b.setAttribute("aria-pressed", String(settings.get(b.dataset.setting) === b.dataset.value));
  });
  el.querySelectorAll("[data-requires]").forEach((r) => {
    const on = !!settings.get(r.dataset.requires);
    r.classList.toggle("disabled", !on);
    r.querySelectorAll("button, input, select").forEach((c) => { c.disabled = !on; });
  });
  for (const key of ["wifiQuality", "cellularQuality"]) {
    const d = el.querySelector(`[data-detail="${key}"]`);
    if (d) d.textContent = qualityDetail(key, settings.get(key));
  }
  const cfr = el.querySelector('input[data-setting="crossfade"]');
  if (cfr) cfr.style.setProperty("--pct", `${(settings.get("crossfade") / 12) * 100}%`);
  const out = el.querySelector('[data-out="crossfade"]');
  if (out) out.textContent = crossfadeLabel(settings.get("crossfade"));
  const eq = el.querySelector('[data-detail="eq"]');
  if (eq) eq.textContent = `Equalizer: ${eqSummary()}`;
}

// ---------- mixer ----------

export function mixerView(el) {
  setTracks([], null);
  const gains = settings.get("eqGains");
  const preset = settings.get("eqPreset");
  const bal = settings.get("balance");
  el.innerHTML = `
    <div class="page mixer">
      <a class="back-link" href="#/settings" data-action="back"><svg><use href="#i-back"/></svg>Back</a>
      <header class="page-head">
        <div><h1 class="page-title">Mixer</h1><p class="page-sub">Shape the sound on this device.</p></div>
        <label class="switch-label">Equalizer ${sw("eqEnabled", "Equalizer")}</label>
      </header>

      <section class="eq-panel" id="eq-panel">
        <div class="eq-top">
          <label class="sr-only" for="eq-preset">Preset</label>
          <select class="select" id="eq-preset">
            ${preset === "Custom" ? `<option value="Custom" selected>Custom</option>` : ""}
            ${Object.keys(EQ_PRESETS).map((name) => `<option value="${esc(name)}"${name === preset ? " selected" : ""}>${esc(name)}</option>`).join("")}
          </select>
          <button class="btn" type="button" data-action="eq-reset">Reset</button>
        </div>
        <div class="eq-graph"><canvas id="eq-canvas" aria-label="Equalizer curve. Drag the points to adjust each band." role="img"></canvas></div>
        <div class="faders">
          ${EQ_BANDS.map((f, i) => `
            <div class="fader">
              <output id="eq-out-${i}">${fmtDb(gains[i])}</output>
              <div class="fader-slot"><input type="range" class="vfader" min="-12" max="12" step="0.5" value="${gains[i]}" data-band="${i}" aria-label="${f >= 1000 ? `${f / 1000} kHz` : `${f} Hz`}" aria-valuetext="${fmtDb(gains[i])} decibels"></div>
              <span class="fader-freq">${f >= 1000 ? `${f / 1000}k` : f}</span>
            </div>`).join("")}
        </div>
      </section>

      <h2 class="settings-section">Balance</h2>
      <div class="balance-row">
        <span>L</span>
        <input type="range" class="range balance" min="-1" max="1" step="0.05" value="${bal}" data-setting="balance" aria-label="Balance" aria-valuetext="${balanceLabel(bal)}">
        <span>R</span>
        <output data-out="balance">${balanceLabel(bal)}</output>
      </div>
      ${row("Mono audio", "Plays the left and right channels through both speakers.", sw("mono", "Mono audio"))}
      ${IS_IOS ? IOS_NOTE : ""}
    </div>`;
}

/** Long page titles (a deluxe edition, radio for a long song name) are set smaller. */
const titleFit = (t = "") => (t.length > 64 ? " longest" : t.length > 38 ? " longer" : t.length > 22 ? " long" : "");

/** Lists where no song has a measured tempo or key drop those two columns. */
const tempoCls = (tracks) => (tracks.some((t) => t.bpm || t.camelot) ? "" : " no-tempo");

export const fmtDb = (v) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(Math.abs(v) % 1 ? 1 : 0)}`;

// ---------- loading placeholders ----------

export function skeleton(kind) {
  if (kind === "album") {
    return `<div class="album-page"><section class="album-hero"><div class="album-hero-inner"><span class="skel-line short"></span><span class="case skel"></span><div><div class="skel-line big"></div><div class="skel-line short"></div></div></div></section></div>`;
  }
  const cards = Array.from({ length: 12 }, () => `<div class="album-card"><span class="case skel"></span><div class="skel-line"></div><div class="skel-line short"></div></div>`).join("");
  return `<div class="page"><header class="page-head"><div class="skel-line big"></div></header><div class="shelf">${cards}</div></div>`;
}


// ---------- downloads ----------

const dlKey = (kind, id) => (kind === "liked" ? "liked" : `${kind}:${id}`);

/** The download button: an arrow in a ring that fills as the songs arrive. */
export function downloadButton(kind, id = "") {
  return `<button class="icon-btn dl-btn" type="button" data-action="download" data-kind="${kind}" data-id="${id}" data-dl="${dlKey(kind, id)}"
    aria-pressed="false" aria-label="Download" title="Download"><svg class="dl-ring" viewBox="0 0 36 36" aria-hidden="true">
      <circle class="dl-track" cx="18" cy="18" r="15.5"/><circle class="dl-fill" cx="18" cy="18" r="15.5" pathLength="100"/>
      <path class="dl-arrow" d="M18 11v12m-5-5 5 5 5-5"/></svg></button>`;
}

/** Bring download buttons and the downloaded marks on song rows in line with what's saved. */
export function refreshDownloads(root = document) {
  root.querySelectorAll(".dl-btn").forEach((b) => {
    const st = offline.state(b.dataset.dl);
    const done = st.saved && !st.downloading;
    b.classList.toggle("saved", st.saved);
    b.classList.toggle("busy", st.saved && st.downloading);
    b.style.setProperty("--dl", String(Math.round(st.progress * 100)));
    b.setAttribute("aria-pressed", String(st.saved));
    const label = !st.saved ? "Download" : done ? "Downloaded. Select to remove the download"
      : `Downloading, ${st.done} of ${st.total} songs`;
    b.setAttribute("aria-label", label);
    b.title = !st.saved ? "Download" : done ? (st.failed ? `Downloaded, except ${plural(st.failed, "song")} that couldn’t be saved` : "Remove download") : `Downloading ${st.done} of ${st.total}`;
  });
  root.querySelectorAll(".track-row[data-track]").forEach((r) => r.classList.toggle("dl", offline.has(Number(r.dataset.track))));
}

function downloadRow(c) {
  const st = offline.state(c.key);
  const href = c.kind === "liked" ? "#/liked" : `#/${c.kind}/${c.id}`;
  const art = c.kind === "liked" ? likedCover("lib-cover")
    : c.kind === "playlist" ? playlistCover(c.data, { cls: "lib-cover" })
    : caseHtml(c.data, { size: 160, cls: "case-sm", sizes: "56px" });
  const what = c.kind === "album" ? `Album, ${esc(c.data.artist)}` : `Playlist, ${plural(c.trackIds.length, "song")}`;
  const status = st.downloading ? `Downloading ${st.done} of ${st.total}` : st.failed ? `${plural(st.failed, "song")} couldn’t be saved` : "";
  return `
    <div class="dl-row">
      <a class="dl-link" href="${href}">
        ${art}
        <span class="lib-text"><span class="lib-name">${esc(c.title)}</span><span class="lib-sub">${what}${status ? `<span class="dl-status">${status}</span>` : ""}</span></span>
      </a>
      ${downloadButton(c.kind, c.id)}
    </div>`;
}

/** Everything downloaded to this device. It's also what Home shows with no connection. */
export async function downloadsView(el) {
  await offline.ready;
  setTracks([], null);
  const list = offline.list();
  const bytes = await offline.usage();
  const pending = offline.pending;
  el.innerHTML = `
    <div class="page downloads">
      <header class="page-head"><h1 class="page-title">Downloads</h1></header>
      <p class="dl-summary">${list.length
        ? `${plural(offline.count(), "song")} on this device, ${fmtBytes(bytes)}.${pending ? ` ${plural(pending, "song")} still to download.` : ""}`
        : ""}</p>
      ${list.length ? `<div class="dl-list">${list.map(downloadRow).join("")}</div>` : `
        <div class="empty"><strong>Nothing downloaded yet</strong>
          Use the download button on an album, a playlist or Favourites to keep it on this device and play it with no connection.</div>`}
    </div>`;
  refreshDownloads(el);
}


// ---------- made for you ----------

/** A mix's cover: its albums, with a band in the mix's colour carrying its name. */
// A mix is a tape: a cassette with a hand-written label in the mix's colour, lying on the
// card insert that shows its albums. The reels turn while it plays (and when pointed at).
const TAPE_SHELL = `<svg class="tape-shell" viewBox="0 0 200 126" aria-hidden="true">
  <rect class="t-body" x="1" y="1" width="198" height="124" rx="9"/>
  <path class="t-foot" d="M40 125 49 97h102l9 28z"/>
  <g class="t-screw"><circle cx="9" cy="9" r="3"/><circle cx="191" cy="9" r="3"/><circle cx="9" cy="117" r="3"/><circle cx="191" cy="117" r="3"/><circle cx="100" cy="117" r="2.6"/></g>
  <g class="t-hole"><circle cx="64" cy="111" r="4.2"/><circle cx="136" cy="111" r="4.2"/><rect x="93" y="101" width="14" height="7" rx="2"/></g>
  <rect class="t-paper" x="13" y="8" width="174" height="82" rx="4"/>
  <rect class="t-band" x="13" y="48" width="174" height="30"/>
  <path class="t-rule" d="M24 41h152"/>
  <text class="t-side" x="21" y="24">A</text>
  <text class="t-print" x="179" y="22" text-anchor="end">C90</text>
  <rect class="t-window" x="48" y="52" width="104" height="22" rx="11"/>
  <circle class="t-pack" cx="72" cy="63" r="10.5"/><circle class="t-pack" cx="128" cy="63" r="7.2"/>
  <g class="t-reel" style="--x:72px"><circle cx="72" cy="63" r="5.6"/><path d="M72 58.6v2M72 65.4v2M68.2 60.8l1.7 1M74.1 64.2l1.7 1M68.2 65.2l1.7-1M74.1 61.8l1.7-1"/></g>
  <g class="t-reel" style="--x:128px"><circle cx="128" cy="63" r="5.6"/><path d="M128 58.6v2M128 65.4v2M124.2 60.8l1.7 1M130.1 64.2l1.7 1M124.2 65.2l1.7-1M130.1 61.8l1.7-1"/></g>
  <rect class="t-glass" x="48" y="52" width="104" height="9" rx="4.5"/>
</svg>`;

export function mixCover(m, { cls = "", size = 160, href = m.key ? `#/mix/${m.key}` : "" } = {}) {
  const c = (m.covers || []).slice(0, 4);
  const img = (x) => `<img src="${coverUrl(x.albumId, x.cover, Math.min(size, 160))}" alt="" loading="lazy" decoding="async">`;
  const len = m.name.length; // long names (radio for a long song title) are written smaller
  const fit = len > 30 ? " longer" : len > 14 ? " long" : "";
  return `<span class="mix-cover mix-tape ${cls}" style="--mix:${esc(m.color)}" data-href="${esc(href)}">
    <span class="tape-card">${c.map(img).join("")}</span>
    <span class="tape">${TAPE_SHELL}<span class="tape-title${fit}"><span>${esc(m.name)}</span></span></span>
  </span>`;
}

function mixCard(m) {
  return `
    <div class="album-card mix-card">
      <div class="card-art">
        <a href="#/mix/${m.key}" aria-label="${esc(m.name)}">${mixCover(m)}</a>
        <button class="card-play" type="button" data-action="play-mix" data-key="${m.key}" aria-label="Play ${esc(m.name)}"><svg><use href="#i-play"/></svg></button>
      </div>
      <div class="card-title"><a href="#/mix/${m.key}">${esc(m.name)}</a></div>
      <div class="card-sub">${esc(m.description)}</div>
    </div>`;
}

/** A Shelf Mix, On Repeat, Discover and the rest, or song or artist radio. */
export async function mixView(el, route) {
  const m = route.blend ? await api.blend(route.blend)
    : route.radio ? await api.radio(route.radio, route.value)
    : await api.mix(route.key);
  const href = route.blend ? `#/blend/${route.blend}` : route.radio ? `#/radio/${route.radio}/${encodeURIComponent(route.value)}` : `#/mix/${m.key}`;
  // A Blend says whose taste each song comes from.
  if (m.kind === "blend") for (const t of m.tracks) t.byLine = t.blendFor === "you" ? "For you" : t.blendFor === "them" ? `For ${m.with}` : "For both of you";
  setTracks(m.tracks, { label: m.name, href });
  ctx.mix = m;
  const secs = m.tracks.reduce((n, t) => n + (t.duration || 0), 0);
  const kind = route.radio ? "Radio" : m.kind === "blend" ? "Blend" : m.kind === "daily" ? "Made for you" : "Playlist";
  el.innerHTML = `
    <div class="album-page playlist-page mix-page">
      <section class="album-hero pl-hero">
        <div class="album-hero-inner">
          <a class="back-link" href="#/" data-action="back"><svg><use href="#i-back"/></svg>Back</a>
          ${mixCover(m, { cls: "pl-cover-lg", size: 320, href })}
          <div>
            <p class="hero-kind">${kind}</p>
            <h1 class="album-title${titleFit(m.name)}">${esc(m.name)}</h1>
            <p class="pl-desc">${esc(m.description)}</p>
            ${m.kind === "blend" && m.match != null ? `<p class="blend-match"><b>${m.match}%</b> taste match</p>` : ""}
            <p class="album-facts">${plural(m.tracks.length, "song")}, ${fmtLength(secs)}${m.kind === "daily" || m.kind === "blend" ? ", new every day" : ""}</p>
            <div class="album-actions">
              <button class="btn btn-primary" type="button" data-action="play-list"><svg><use href="#i-play"/></svg>Play</button>
              <button class="btn squeeze" type="button" data-action="shuffle-list"><svg><use href="#i-shuffle"/></svg><span class="btn-text">Shuffle</span></button>
              <button class="btn squeeze" type="button" data-action="mix-save"><svg><use href="#i-plus"/></svg><span class="btn-text">Save as playlist</span></button>
            </div>
          </div>
        </div>
      </section>
      <div class="tracklist pl-tracks${tempoCls(m.tracks)}">
        <div class="track-head pl-head" aria-hidden="true"><span>#</span><span>Title</span><span class="pl-bpm">BPM</span><span class="pl-key">Key</span><span class="pl-album">Album</span><span class="pl-added"></span><span></span><span><svg><use href="#i-clock"/></svg></span></div>
        ${m.tracks.map(playlistRow).join("")}
      </div>
    </div>`;
  applyAlbumColor(el, /^#[0-9a-f]{6}$/i.test(m.color) ? m.color : null);
}

// ---------- people ----------

const whenAgo = (ts) => {
  const m = Math.round((Date.now() / 1000 - ts) / 60);
  if (m < 2) return "just now";
  if (m < 60) return `${m} min`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} hr`;
  const d = Math.round(h / 24);
  return d < 7 ? `${d} d` : `${Math.round(d / 7)} wk`;
};

export const personDisc = (name) => {
  const parts = name.trim().split(/\s+/);
  const ini = (parts.length > 1 ? parts[0][0] + parts[parts.length - 1][0] : name.slice(0, 2)).toUpperCase();
  return `<span class="person-disc" style="--disc:${fallbackColor(name)}" aria-hidden="true"><span>${esc(ini)}</span></span>`;
};

function activityRow(a, canBlend) {
  const live = a.now;
  const t = live?.track ?? a.last?.track;
  const ctxLink = live?.context?.href && live.context.label
    ? `<a class="act-context" href="${esc(live.context.href)}">${esc(live.context.label)}</a>` : `<a class="act-context" href="#/album/${t.albumId}">${esc(t.album)}</a>`;
  const status = live?.playing
    ? `<span class="act-live"><span class="eq-bars" aria-hidden="true"><i></i><i></i><i></i></span>Listening now${live.device ? ` on ${esc(live.device)}` : ""}</span>`
    : `<span class="act-when">${a.last ? whenAgo(live ? Date.now() / 1000 : a.last.at) : ""}</span>`;
  return `
    <li class="act-row">
      ${personDisc(a.user.username)}
      <span class="act-text">
        <span class="act-name">${esc(a.user.username)}</span>
        <button class="act-track" type="button" data-action="act-play" data-track="${t.id}" title="Play ${esc(t.title)}">${esc(t.title)} <span>• ${esc(t.artist)}</span></button>
        ${ctxLink}
      </span>
      <span class="act-side">${status}
        ${canBlend ? `<a class="btn btn-small" href="#/blend/${a.user.id}"><svg><use href="#i-blend"/></svg>Blend</a>` : ""}</span>
    </li>`;
}

/** Friend activity: what the other people here are playing, and Blends with them. */
export async function peopleView(el) {
  const [activity, people, shared, parties] = await Promise.all([api.activity(), api.people(), api.sharedPlaylists().catch(() => []),
    api.parties().catch(() => [])]);
  setTracks([], null);
  ctx.activity = activity;
  const quiet = people.filter((p) => !activity.some((a) => a.user.id === p.id));
  el.innerHTML = `
    <div class="page people-page">
      <header class="page-head"><div><h1 class="page-title">Friend activity</h1>
        <p class="page-sub">${people.length ? "What everyone on this server is playing" : "Nobody else uses this server yet"}</p></div></header>
      <section class="party-strip">
        ${parties.map((p) => `<a class="party-card" href="#/party/${p.host.id}"><svg><use href="#i-people"/></svg>
          <span><b>${p.mine ? "Your party" : `${esc(p.host.username)}’s party`}</b><small>${p.people} ${p.people === 1 ? "person" : "people"} there${p.joined ? ", you’re in" : ""}</small></span>
          <span class="btn btn-small">${p.mine || p.joined ? "Open" : "Join"}</span></a>`).join("")}
        ${people.length && !parties.some((p) => p.mine) ? `<button class="btn" type="button" data-action="party-start"><svg><use href="#i-plus"/></svg>Start a party</button>
          <p class="page-sub party-hint">Everyone here can join what you’re playing, add songs and vote to skip.</p>` : ""}
      </section>
      ${activity.length ? `<ul class="act-list">${activity.map((a) => activityRow(a, people.find((p) => p.id === a.user.id)?.canBlend)).join("")}</ul>` : ""}
      ${quiet.length ? `<h2 class="section-title people-quiet-title">Also here</h2>
        <ul class="act-list">${quiet.map((p) => `
          <li class="act-row">${personDisc(p.username)}
            <span class="act-text"><span class="act-name">${esc(p.username)}</span><span class="act-when">${p.canBlend ? "Hasn’t played anything yet" : "Keeps their listening to themselves"}</span></span>
            <span class="act-side">${p.canBlend ? `<a class="btn btn-small" href="#/blend/${p.id}"><svg><use href="#i-blend"/></svg>Blend</a>` : ""}</span>
          </li>`).join("")}</ul>` : ""}
      ${shared.length ? `<section class="row-section">
        <div class="row-head"><h2 class="section-title">Shared playlists</h2></div>
        <div class="shelf">${shared.map((p) => `
          <a class="pl-card" href="#/playlist/${p.id}" data-playlist="${p.id}">
            ${playlistCover(p)}
            <span class="card-title">${esc(p.name)}</span>
            <span class="card-sub">By ${esc(p.owner.username)}${p.shared === 2 ? ", collaborative" : ""}</span>
          </a>`).join("")}</div>
      </section>` : ""}
      ${!people.length ? `<div class="empty"><strong>It’s just you so far</strong>An admin can add people from the admin dashboard. Then you’ll see what they’re playing here, and can make a Blend together.</div>` : ""}
    </div>`;
}


// ---------- new releases ----------

const RELEASE_TYPE = { Album: "Album", EP: "EP", Single: "Single" };

/** An album or EP by one of your artists that isn't on the shelf: its cover links to MusicBrainz. */
function releaseCard(r) {
  const year = r.date.slice(0, 4);
  const url = `https://musicbrainz.org/release-group/${r.mbid}`;
  return `
    <div class="album-card release-card">
      <div class="card-art">
        <a href="${url}" target="_blank" rel="noopener" aria-label="${esc(r.title)} on MusicBrainz">
          <span class="case release-case" style="--case-bg:${fallbackColor(r.title)}"><span class="no-art">${esc(r.title)}</span>
            <img src="api/releases/${r.mbid}/cover" alt="" loading="lazy" onerror="this.remove()" onload="this.classList.add('ld')"></span>
        </a>
      </div>
      <div class="card-title"><a href="${url}" target="_blank" rel="noopener">${esc(r.title)}</a></div>
      <div class="card-sub"><a href="${artistHref(r.artist)}">${esc(r.artist)}</a>, ${year}${r.type !== "Album" ? `, ${RELEASE_TYPE[r.type] ?? r.type}` : ""}</div>
    </div>`;
}

/** Everything your artists have out that isn't on the shelf, newest first, by artist. */
export async function releasesView(el, { admin = false } = {}) {
  const r = await api.releases();
  setTracks([], null);
  const byArtist = new Map();
  for (const x of r.releases) {
    if (!byArtist.has(x.artist)) byArtist.set(x.artist, []);
    byArtist.get(x.artist).push(x);
  }
  const when = r.checkedAt ? new Date(r.checkedAt * 1000).toLocaleDateString(undefined, { day: "numeric", month: "long" }) : null;
  el.innerHTML = `
    <div class="page releases-page"${r.state?.running ? " data-running" : ""}>
      <header class="page-head"><div>
        <h1 class="page-title">Not on your shelf</h1>
        <p class="page-sub">${r.off ? "Turned off on this server (artist_info in config.toml)."
          : r.state?.running ? `Checking MusicBrainz: ${r.state.checked} of ${r.state.total} artists…`
          : when ? `Albums and EPs by your artists that you don’t have yet, from MusicBrainz. Checked ${when}.`
          : "Shelf checks MusicBrainz for your artists’ albums once a day. The first check is on its way."}</p></div>
        ${admin && !r.off ? `<div class="head-tools"><button class="btn" type="button" data-action="releases-check" ${r.state?.running ? "disabled" : ""}>Check now</button></div>` : ""}
      </header>
      ${[...byArtist].map(([artist, list]) => `
        <section class="row-section">
          <div class="row-head"><h2 class="section-title"><a href="${artistHref(artist)}">${esc(artist)}</a></h2><span class="page-sub">${plural(list.length, "release")}</span></div>
          <div class="row-shelf">${list.map(releaseCard).join("")}</div>
        </section>`).join("") || (when ? `<div class="empty"><strong>You have it all</strong>Every album and EP your artists have out is on your shelf.</div>` : "")}
    </div>`;
}


/** The DJ: first in Made for you. */
function djCard() {
  return `
    <div class="album-card mix-card dj-card">
      <div class="card-art">
        <button class="dj-cover" type="button" data-dj="start" aria-label="Start your DJ">
          <span class="dj-word">DJ</span><span class="dj-waves" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></span>
        </button>
        <button class="card-play" type="button" data-dj="start" aria-label="Start your DJ"><svg><use href="#i-play"/></svg></button>
      </div>
      <div class="card-title"><button class="text-btn" type="button" data-dj="start">DJ</button></div>
      <div class="card-sub">Shelf Radio: your music, with a host who knows what you like</div>
    </div>`;
}


// ---------- your listening (stats) and Wrapped ----------

const PERIOD_LABEL = { month: "This month", year: "This year", all: "All time" };
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const titleCase = (s) => s.replace(/\b\w/g, (c) => c.toUpperCase());
const fmtDay = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
const hoursText = (min) => (min >= 120 ? `${Math.round(min / 60).toLocaleString()} hours` : plural(min, "minute"));

/** Bars for plays by hour or weekday, the busiest one marked. */
function bars(counts, labels, cls) {
  const top = Math.max(1, ...counts);
  const peak = counts.indexOf(Math.max(...counts));
  return `<div class="stat-bars ${cls}" role="img" aria-label="${esc(labels.map((l, i) => `${l}: ${counts[i]}`).join(", "))}">${counts.map((n, i) => `
    <span class="stat-bar${i === peak && n ? " peak" : ""}"><span style="height:${Math.round((n / top) * 100)}%"></span><small>${esc(labels[i])}</small></span>`).join("")}</div>`;
}

function listenerKind(hours) {
  const at = (from, to) => hours.slice(from, to).reduce((a, b) => a + b, 0);
  const total = hours.reduce((a, b) => a + b, 0) || 1;
  if ((at(22, 24) + at(0, 4)) / total > 0.3) return "a night owl: a lot of your listening happens after 10 pm";
  if (at(5, 10) / total > 0.3) return "an early bird: a lot of your listening happens before 10 am";
  const peak = hours.indexOf(Math.max(...hours));
  return `most often listening around ${peak === 0 ? "midnight" : peak === 12 ? "noon" : peak < 12 ? `${peak} am` : `${peak - 12} pm`}`;
}

export async function statsView(el, period = "year") {
  const s = await api.stats(period);
  const tracks = [...s.topSongs, ...s.onThisDay];
  setTracks(tracks, { label: "Your top songs", href: "#/stats" });
  const periods = ["month", "year", "all", ...s.years.slice(1).map(String)];
  const label = PERIOD_LABEL[period] ?? period;
  const year = s.years[0];
  const hours = Array.from({ length: 24 }, (_, h) => (h % 6 === 0 ? `${h}` : ""));
  const empty = !s.plays;
  el.innerHTML = `
    <div class="page stats-page">
      <header class="page-head"><div><h1 class="page-title">Your listening</h1>
        <p class="page-sub">${empty ? "Nothing played in this period yet" : `${hoursText(s.minutes)} of music: ${plural(s.plays, "play")} of ${plural(s.songs, "song")} by ${plural(s.artists, "artist")}.`}</p></div>
        ${year ? `<a class="btn btn-primary" href="#/wrapped/${year}"><svg><use href="#i-sparkle"/></svg>Your ${year} Wrapped</a>` : ""}
      </header>
      <div class="chips stats-periods">${periods.map((p) => `<a class="chip" href="#/stats?period=${p}" aria-pressed="${p === period}">${esc(PERIOD_LABEL[p] ?? p)}</a>`).join("")}</div>
      ${s.currentStreak || s.longestStreak ? `<p class="stats-streak">${s.currentStreak > 1 ? `You’ve listened ${s.currentStreak} days in a row.` : s.currentStreak ? "You’ve listened today." : "No streak going right now."}
        ${s.longestStreak > 1 ? `Your longest run ${period === "all" ? "ever" : period === "month" ? "this month" : period === "year" ? "this year" : `in ${period}`}: ${s.longestStreak} days.` : ""}</p>` : ""}
      ${empty ? "" : `
      <div class="stats-grid">
        <section class="stats-block"><h2 class="section-title">Top artists</h2>
          <ol class="stats-rank">${s.topArtists.map((a) => `<li><a href="#/artist/${encodeURIComponent(a.name)}">${esc(a.name)}</a><span>${plural(a.plays, "play")}</span></li>`).join("")}</ol>
        </section>
        <section class="stats-block"><h2 class="section-title">When you listen</h2>
          <p class="stats-note">You’re ${listenerKind(s.hours)}.</p>
          ${bars(s.hours, hours, "hours")}
          ${bars(s.weekdays, WEEKDAYS, "weekdays")}
          ${s.busiestDay ? `<p class="stats-note">Busiest day: ${esc(fmtDay(s.busiestDay.date))}, ${plural(s.busiestDay.plays, "play")}.</p>` : ""}
        </section>
      </div>
      <section class="row-section"><div class="row-head"><h2 class="section-title">Top songs</h2>
        <button class="see-all" type="button" data-action="play-top" data-count="${s.topSongs.length}">Play them</button></div>
        <div class="track-list stats-songs">${s.topSongs.map((t, i) => trackRow(t, i, { withArt: true }).replace('<span class="t-sub">', `<span class="t-sub">${plural(t.plays, "play")}, `)).join("")}</div>
      </section>
      ${rowShelf("Top albums", s.topAlbums)}
      ${s.topGenres.length ? `<section class="row-section"><h2 class="section-title">Top genres</h2>
        <div class="chips">${s.topGenres.map((g) => `<span class="chip stats-chip">${esc(titleCase(g.name))}<small>${g.plays}</small></span>`).join("")}</div></section>` : ""}
      ${s.newArtists.length && period !== "all" ? `<section class="row-section"><h2 class="section-title">New to you ${esc(label.toLowerCase())}</h2>
        <p class="stats-note">${plural(s.newArtists.length, "artist")} you hadn’t played before.</p>
        <div class="chips">${s.newArtists.slice(0, 24).map((a) => `<a class="chip" href="#/artist/${encodeURIComponent(a)}">${esc(a)}</a>`).join("")}</div></section>` : ""}`}
      ${s.onThisDay.length ? `<section class="row-section"><h2 class="section-title">On this day, a year ago</h2>
        <div class="track-list">${s.onThisDay.map((t, i) => trackRow(t, s.topSongs.length + i, { withArt: true })).join("")}</div></section>` : ""}
    </div>`;
}

/** Your year in music: one card at a time. */
export async function wrappedView(el, year) {
  const s = await api.stats(String(year));
  setTracks(s.topSongs, { label: `Your top songs of ${year}`, href: `#/wrapped/${year}` });
  const top = s.topArtists[0];
  const cards = !s.plays ? [`<h2>Nothing played in ${year}</h2><p>Play some music and come back.</p>`] : [
    `<p class="w-kicker">${year}, in music</p><h2>You listened for ${hoursText(s.minutes)}.</h2><p>${plural(s.plays, "play")} of ${plural(s.songs, "song")} by ${plural(s.artists, "artist")}.</p>`,
    top && `<p class="w-kicker">Your artist of the year</p><h2>${esc(top.name)}</h2><p>${plural(top.plays, "play")}, ${hoursText(top.minutes)} together.</p>
      ${s.topArtists.length > 1 ? `<ol class="w-list">${s.topArtists.slice(1, 5).map((a) => `<li>${esc(a.name)}</li>`).join("")}</ol>` : ""}`,
    s.topSongs.length && `<p class="w-kicker">Your top songs</p><ol class="w-list w-songs">${s.topSongs.slice(0, 5).map((t) => `<li><b>${esc(t.title)}</b><span>${esc(t.artist)}, ${plural(t.plays, "play")}</span></li>`).join("")}</ol>`,
    s.topGenres.length && `<p class="w-kicker">What it sounded like</p><h2>${esc(titleCase(s.topGenres[0].name))}</h2>
      ${s.topGenres.length > 1 ? `<p>Then ${esc(s.topGenres.slice(1, 4).map((g) => titleCase(g.name)).join(", "))}.</p>` : ""}`,
    s.newArtists.length && `<p class="w-kicker">New to you</p><h2>${plural(s.newArtists.length, "artist")} you hadn’t played before</h2><p>${esc(s.newArtists.slice(0, 6).join(", "))}${s.newArtists.length > 6 ? " and more" : ""}.</p>`,
    `<p class="w-kicker">When you listened</p><h2>You’re ${listenerKind(s.hours).split(":")[0]}.</h2>
      ${s.busiestDay ? `<p>Your busiest day was ${esc(fmtDay(s.busiestDay.date))}, with ${plural(s.busiestDay.plays, "play")}.</p>` : ""}
      ${s.longestStreak > 1 ? `<p>Longest run: ${s.longestStreak} days in a row.</p>` : ""}`,
    `<p class="w-kicker">That was ${year}</p><h2>Play your top songs</h2><p><button class="btn btn-primary" type="button" data-action="play-list"><svg><use href="#i-play"/></svg>Play</button></p>`,
  ].filter(Boolean);
  el.innerHTML = `
    <div class="page wrapped-page">
      <a class="back-link" href="#/stats"><svg><use href="#i-back"/></svg>Your listening</a>
      <div class="w-deck" data-at="0">
        ${cards.map((c, i) => `<section class="w-card w-c${i % 5}" ${i ? "hidden" : ""} aria-label="${i + 1} of ${cards.length}">${c}</section>`).join("")}
      </div>
      <div class="w-nav">
        <button class="btn" type="button" data-action="wrapped-step" data-step="-1">Back</button>
        <span class="w-count">1 of ${cards.length}</span>
        <button class="btn btn-primary" type="button" data-action="wrapped-step" data-step="1">Next</button>
      </div>
    </div>`;
}

/** Wrapped: show the card `step` away from the current one. */
export function wrappedStep(el, step) {
  const deck = el.querySelector(".w-deck");
  if (!deck) return;
  const cards = [...deck.children];
  const at = Math.min(cards.length - 1, Math.max(0, Number(deck.dataset.at) + step));
  deck.dataset.at = String(at);
  cards.forEach((c, i) => { c.hidden = i !== at; });
  el.querySelector(".w-count").textContent = `${at + 1} of ${cards.length}`;
}


// ---------- party mode ----------

/** Someone's party: what's playing, vote to skip, up next, and songs to add. Redrawn every few seconds. */
export async function partyView(el, host) {
  const p = await api.party(host);
  if (!p.joined) await api.joinParty(host);
  // A guest plays along (Play here), unless they turned it off at this party.
  if (!p.isHost && store.get("party", null)?.host !== host) store.set("party", { host, playHere: true });
  const playHere = !p.isHost && !!store.get("party", null)?.playHere;
  const now = p.nowPlaying;
  const prior = el.querySelector("#party-find")?.value ?? "";
  setTracks(p.upNext, { label: `${p.host.username}’s party`, href: `#/party/${host}` });
  el.innerHTML = `
    <div class="page party-page" data-host="${host}">
      <header class="page-head"><div><h1 class="page-title">${p.isHost ? "Your party" : `${esc(p.host.username)}’s party`}</h1>
        <p class="page-sub">${esc(p.members.join(", "))}</p>
        ${p.isHost ? "" : `<label class="party-here"><button class="switch" type="button" role="switch" data-action="party-here" aria-checked="${playHere}" aria-label="Play here"></button>
          <span><b>Play here</b><small>Hear it on this device, in step with ${esc(p.host.username)}. Turn it off when you’re in the same room.</small></span></label>`}</div>
        ${p.isHost ? `<button class="btn" type="button" data-action="party-end">End party</button>`
                   : `<button class="btn" type="button" data-action="party-leave">Leave party</button>`}
      </header>
      ${now ? `<section class="party-now">
        ${caseHtml(now, { size: 320, cls: "party-case" })}
        <div><p class="hero-kind">${p.playing ? "Playing now" : "Paused"}</p>
          <h2 class="party-title">${esc(now.title)}</h2><p class="page-sub">${esc(now.artist)}, ${esc(now.album ?? "")}</p>
          <p><button class="btn${p.youVoted ? "" : " btn-primary"}" type="button" data-action="party-skip"${p.youVoted ? " disabled" : ""}>
            <svg><use href="#i-next"/></svg>${p.youVoted ? "You voted to skip" : "Vote to skip"}</button>
            <span class="party-votes">${p.votes} of ${p.needed} ${p.needed === 1 ? "vote" : "votes"} to skip</span></p></div>
      </section>` : `<div class="empty"><strong>Nothing’s playing yet</strong>${p.isHost ? "Play something on any of your devices, and it plays here." : `When ${esc(p.host.username)} plays something, it shows here.`}</div>`}
      <section class="row-section"><h2 class="section-title">Add songs</h2>
        <label class="search-box"><span class="sr-only">Search for songs to add</span><svg><use href="#i-search"/></svg>
          <input id="party-find" type="search" placeholder="Search for a song" autocomplete="off" value="${esc(prior)}"></label>
        <div id="party-found" class="track-list"></div>
      </section>
      ${p.upNext.length ? `<section class="row-section"><h2 class="section-title">Up next</h2>
        <div class="track-list">${p.upNext.map((t, i) => trackRow(t, i, { withArt: true })).join("")}</div></section>` : ""}
    </div>`;
  const input = el.querySelector("#party-find");
  const out = el.querySelector("#party-found");
  let timer;
  const run = async () => {
    const q = input.value.trim();
    if (!q) { out.innerHTML = ""; return; }
    const r = await api.search(q);
    if (input.value.trim() !== q) return;
    out.innerHTML = r.tracks.length ? r.tracks.slice(0, 12).map((t) => `
      <div class="track-row with-art pl-add-row" data-track="${t.id}">
        ${caseHtml(t, { size: 160, cls: "case-sm" })}
        <span class="t-main"><span class="t-title">${esc(t.title)}</span><span class="t-sub">${esc(t.artist)}, ${esc(t.album)}</span></span>
        <span></span>
        <button class="btn btn-small" type="button" data-action="party-add" data-track="${t.id}">Add</button>
      </div>`).join("") : `<p class="page-sub">No songs match “${esc(q)}”.</p>`;
  };
  input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => run().catch(() => {}), 180); });
  if (prior) { input.focus(); await run().catch(() => {}); }
}
