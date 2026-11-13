// Requests (see src/shelf/requests.py): ask for an artist or a particular album. Everyone in the
// household sees the list, admins mark requests done or declined, and a scan that brings the
// music in ticks the request off by itself. While you type, MusicBrainz suggests the exact
// artist or album, so a request carries its year, cover and a link.

import { api } from "./api.js";
import { artistHref } from "./views.js";
import { esc, fallbackColor, toast } from "./util.js";

const STATUS_LABEL = { open: "Asked for", done: "On the shelf", declined: "Not this one" };
const MB_SITE = "https://musicbrainz.org";

function when(ts) {
  return new Date(ts * 1000).toLocaleDateString(undefined, { day: "numeric", month: "long" });
}

/** A small cover from the Cover Art Archive (through the server), the artist's photo when it's
 * the artist that's asked for, or the title's colour. */
function thumb(albumId, title, cls = "req-cover", artist = null) {
  const src = albumId ? `api/releases/${albumId}/cover` : artist ? `api/artist/image?find=1&name=${encodeURIComponent(artist)}` : null;
  return `<span class="${cls}${albumId ? "" : " req-artist"}" style="--case-bg:${fallbackColor(title || "?")}" aria-hidden="true">${src
    ? `<img src="${src}" alt="" loading="lazy" onerror="this.remove()" onload="this.classList.add('ld')">` : ""}</span>`;
}

const details = (x) => [x.year, x.type && x.type !== "Album" ? x.type : null, x.extra].filter(Boolean).join(" · ");

function row(r, admin) {
  const what = r.album ? `<strong>${esc(r.album)}</strong> by ${esc(r.artist)}` : `<strong>${esc(r.artist)}</strong> — anything`;
  const name = r.status === "done" ? `<a href="${artistHref(r.artist)}">${what}</a>` : what;
  const more = details(r);
  const mb = r.albumId ? `${MB_SITE}/release-group/${r.albumId}` : r.artistId ? `${MB_SITE}/artist/${r.artistId}` : null;
  return `
    <li class="hook request-row${r.status !== "open" ? " settled" : ""}">
      ${thumb(r.albumId, r.album || r.artist, "req-cover", r.album ? null : r.artist)}
      <div class="hook-main">
        <span class="hook-url">${name}${more ? ` <span class="req-more">${esc(more)}</span>` : ""}</span>
        ${r.note ? `<span class="hook-events">“${esc(r.note)}”</span>` : ""}
        <span class="hook-status">${STATUS_LABEL[r.status]} · ${r.mine ? "you" : esc(r.requestedBy)}, ${when(r.createdAt)}${mb
          ? ` · <a href="${mb}" target="_blank" rel="noopener">MusicBrainz</a>` : ""}</span>
      </div>
      <div class="hook-actions">
        ${admin && r.status === "open" ? `
          <button class="btn btn-small" type="button" data-req="done" data-id="${r.id}">It’s on the shelf</button>
          <button class="btn btn-small" type="button" data-req="declined" data-id="${r.id}">Decline</button>` : ""}
        ${admin && r.status !== "open" ? `<button class="btn btn-small" type="button" data-req="open" data-id="${r.id}">Reopen</button>` : ""}
        ${r.mine || admin ? `<button class="icon-btn" type="button" data-req="remove" data-id="${r.id}" aria-label="Withdraw this request" title="Withdraw"><svg><use href="#i-trash"/></svg></button>` : ""}
      </div>
    </li>`;
}

/**
 * Suggestions under a text field, as you type: arrow keys move, Enter picks, Escape closes.
 * `fetch(text)` gives {results, error}; `item(x)` draws one; `pick(x)` is called with the chosen one.
 */
function suggest(input, { fetch, item, pick, openOnFocus = () => false }) {
  const list = document.createElement("ul");
  list.className = "mb-list";
  list.id = `${input.name}-suggest`;
  list.setAttribute("role", "listbox");
  list.hidden = true;
  input.after(list);
  input.setAttribute("role", "combobox");
  input.setAttribute("aria-autocomplete", "list");
  input.setAttribute("aria-controls", list.id);
  input.setAttribute("aria-expanded", "false");
  let results = [];
  let active = -1;
  let seq = 0;
  let timer = 0;

  const close = () => {
    list.hidden = true;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    active = -1;
  };
  const mark = () => {
    list.querySelectorAll("[role=option]").forEach((li, i) => li.setAttribute("aria-selected", String(i === active)));
    if (active >= 0) {
      input.setAttribute("aria-activedescendant", `${list.id}-${active}`);
      list.children[active]?.scrollIntoView({ block: "nearest" });
    } else input.removeAttribute("aria-activedescendant");
  };
  const show = (html) => {
    list.innerHTML = html;
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
  };
  const run = async () => {
    const mine = ++seq;
    const text = input.value;
    show(`<li class="mb-note">Looking on MusicBrainz…</li>`);
    let r;
    try { r = await fetch(text); } catch (e) { r = { results: [], error: e.message }; }
    if (mine !== seq || document.activeElement !== input) return;
    if (!r) { close(); return; }
    results = r.results || [];
    active = -1;
    if (r.error) show(`<li class="mb-note">${esc(r.error)}</li>`);
    else if (!results.length) show(`<li class="mb-note">MusicBrainz doesn’t know this one. You can still ask for it as typed.</li>`);
    else show(results.map((x, i) => `<li role="option" id="${list.id}-${i}" data-i="${i}" aria-selected="false">${item(x)}</li>`).join(""));
  };
  const soon = () => { clearTimeout(timer); timer = setTimeout(run, 300); };

  input.addEventListener("input", soon);
  input.addEventListener("focus", () => { if (openOnFocus()) run(); });
  input.addEventListener("blur", () => setTimeout(close, 150));
  input.addEventListener("keydown", (e) => {
    if (list.hidden || !results.length) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const n = list.querySelectorAll("[role=option]").length;
      active = e.key === "ArrowDown" ? (active + 1) % n : (active <= 0 ? n - 1 : active - 1);
      mark();
    } else if (e.key === "Enter" && active >= 0) {
      e.preventDefault();
      pick(results[active]);
      close();
    } else if (e.key === "Escape") {
      e.preventDefault();
      close();
    }
  });
  list.addEventListener("mousedown", (e) => e.preventDefault()); // keep the field focused
  list.addEventListener("click", (e) => {
    const li = e.target.closest("[data-i]");
    if (!li) return;
    pick(results[Number(li.dataset.i)]);
    close();
  });
  return { refresh: run, close };
}

const shelfTag = (x) => (x.onShelf ? `<span class="mb-tag">On the shelf</span>` : "");

function mountForm(form, lookup, done) {
  const f = form.elements;
  const picked = { artistId: null, albumId: null, year: null, type: null };
  const flag = (name, on) => form.querySelector(`[data-field="${name}"]`).classList.toggle("picked", on);
  const clearAlbum = () => { Object.assign(picked, { albumId: null, year: null, type: null }); flag("album", false); };

  if (lookup) {
    suggest(f.artist, {
      fetch: (q) => (q.trim().length < 2 ? null : api.requestLookup({ kind: "artist", q })),
      item: (a) => `<span class="mb-main"><span class="mb-title">${esc(a.name)}</span>${a.about ? `<span class="mb-sub">${esc(a.about)}</span>` : ""}</span>${shelfTag(a)}`,
      pick: (a) => {
        f.artist.value = a.name;
        picked.artistId = a.id;
        flag("artist", true);
        clearAlbum();
        f.album.value = "";
        f.album.placeholder = `Pick one of ${a.name}’s, or type to narrow`;
        f.album.focus(); // shows their albums
      },
    });
    suggest(f.album, {
      fetch: (q) => {
        if (picked.artistId) return api.requestLookup({ kind: "album", q, artistId: picked.artistId, artist: f.artist.value });
        return q.trim().length < 2 ? null : api.requestLookup({ kind: "album", q, artist: f.artist.value });
      },
      item: (a) => `${thumb(a.id, a.title, "mb-cover")}<span class="mb-main"><span class="mb-title">${esc(a.title)}</span>
        <span class="mb-sub">${esc([a.artist && !picked.artistId ? a.artist : null, details(a)].filter(Boolean).join(" · "))}</span></span>${shelfTag(a)}`,
      pick: (a) => {
        f.album.value = a.title;
        Object.assign(picked, { albumId: a.id, year: a.year, type: a.type });
        if (a.artist && a.artistId && !picked.artistId) {
          f.artist.value = a.artist;
          picked.artistId = a.artistId;
          flag("artist", true);
        }
        flag("album", true);
        f.note.focus();
      },
      openOnFocus: () => !!picked.artistId && !picked.albumId,
    });
    f.artist.addEventListener("input", () => {
      picked.artistId = null;
      flag("artist", false);
      clearAlbum();
      f.album.placeholder = "Pick an artist to see their albums";
    });
    f.album.addEventListener("input", clearAlbum);
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const album = f.album.value.trim();
    try {
      await api.addRequest({
        artist: f.artist.value, album: album || null, note: f.note.value || null,
        artistId: picked.artistId, ...(album ? { albumId: picked.albumId, year: picked.year, type: picked.type } : {}),
      });
      toast("Asked. It’ll tick itself off when the music arrives.");
      done();
    } catch (ex) { toast(ex.message); }
  });
}

/** The Requests page: a form to ask with, then everyone's requests, open ones first. */
export async function requestsView(el, { admin = false, artist = "" } = {}) {
  const { requests, lookup } = await api.requests();
  el.innerHTML = `
    <div class="page requests-page">
      <header class="page-head"><div>
        <h1 class="page-title">Requests</h1>
        <p class="page-sub">Missing something? Ask for an artist, or one album in particular. Everyone sees the list, and when the music lands on the shelf the request ticks itself off.</p>
      </div></header>
      <form class="request-form" autocomplete="off">
        <label class="field" data-field="artist"><span>Artist <i class="mb-ok">MusicBrainz ✓</i></span>
          <span class="mb-wrap"><input name="artist" required maxlength="300" value="${esc(artist)}" spellcheck="false"></span></label>
        <label class="field" data-field="album"><span>Album <small>(optional)</small> <i class="mb-ok">MusicBrainz ✓</i></span>
          <span class="mb-wrap"><input name="album" maxlength="300" spellcheck="false" placeholder="${lookup ? "Pick an artist to see their albums" : ""}"></span></label>
        <label class="field request-note"><span>Note <small>(optional)</small></span><input name="note" maxlength="1000" placeholder="the live one, the deluxe one…"></label>
        <div class="request-send">
          <button class="btn btn-primary" type="submit">Ask for it</button>
          ${lookup ? `<span class="field-hint">Suggestions from <a href="${MB_SITE}" target="_blank" rel="noopener">MusicBrainz</a>, the open music encyclopedia.</span>` : ""}
        </div>
      </form>
      ${requests.length
    ? `<ul class="hooks requests-list">${requests.map((r) => row(r, admin)).join("")}</ul>`
    : `<div class="empty"><strong>Nothing asked for yet</strong>When someone wants music the shelf doesn’t have, it goes here.</div>`}
    </div>`;

  const redraw = () => requestsView(el, { admin });
  mountForm(el.querySelector(".request-form"), lookup, redraw);
  el.querySelector(".requests-list")?.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-req]");
    if (!b) return;
    const id = Number(b.dataset.id);
    try {
      if (b.dataset.req === "remove") await api.removeRequest(id);
      else await api.resolveRequest(id, b.dataset.req);
      redraw();
    } catch (ex) { toast(ex.message); }
  });
}
