// Requests (see src/shelf/requests.py): ask for an artist or a particular album. Everyone in the
// household sees the list, admins mark requests done or declined, and a scan that brings the
// music in ticks the request off by itself.

import { api } from "./api.js";
import { artistHref } from "./views.js";
import { esc, toast } from "./util.js";

const STATUS_LABEL = { open: "Asked for", done: "On the shelf", declined: "Not this one" };

function when(ts) {
  return new Date(ts * 1000).toLocaleDateString(undefined, { day: "numeric", month: "long" });
}

function row(r, admin) {
  const what = r.album ? `<strong>${esc(r.album)}</strong> by ${esc(r.artist)}` : `<strong>${esc(r.artist)}</strong> — anything`;
  const name = r.status === "done" ? `<a href="${artistHref(r.artist)}">${what}</a>` : what;
  return `
    <li class="hook request-row${r.status !== "open" ? " settled" : ""}">
      <div class="hook-main">
        <span class="hook-url">${name}</span>
        ${r.note ? `<span class="hook-events">“${esc(r.note)}”</span>` : ""}
        <span class="hook-status">${STATUS_LABEL[r.status]} · ${r.mine ? "you" : esc(r.requestedBy)}, ${when(r.createdAt)}</span>
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

/** The Requests page: a form to ask with, then everyone's requests, open ones first. */
export async function requestsView(el, { admin = false, artist = "" } = {}) {
  const { requests } = await api.requests();
  el.innerHTML = `
    <div class="page requests-page">
      <header class="page-head"><div>
        <h1 class="page-title">Requests</h1>
        <p class="page-sub">Missing something? Ask for an artist, or one album in particular. Everyone sees the list, and when the music lands on the shelf the request ticks itself off.</p>
      </div></header>
      <form class="request-form">
        <label class="field"><span>Artist</span><input name="artist" required maxlength="300" value="${esc(artist)}" autocomplete="off" spellcheck="false"></label>
        <label class="field"><span>Album <small>(optional)</small></span><input name="album" maxlength="300" autocomplete="off" spellcheck="false"></label>
        <label class="field request-note"><span>Note <small>(optional)</small></span><input name="note" maxlength="1000" placeholder="the live one, the deluxe one…" autocomplete="off"></label>
        <button class="btn btn-primary" type="submit">Ask for it</button>
      </form>
      ${requests.length
    ? `<ul class="hooks requests-list">${requests.map((r) => row(r, admin)).join("")}</ul>`
    : `<div class="empty"><strong>Nothing asked for yet</strong>When someone wants music the shelf doesn’t have, it goes here.</div>`}
    </div>`;

  const redraw = () => requestsView(el, { admin });
  el.querySelector(".request-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target.elements;
    try {
      await api.addRequest({ artist: f.artist.value, album: f.album.value || null, note: f.note.value || null });
      toast("Asked. It’ll tick itself off when the music arrives.");
      redraw();
    } catch (ex) { toast(ex.message); }
  });
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
