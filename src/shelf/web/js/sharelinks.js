// Share links: a song, an album or a playlist anyone with the link can listen to, without an
// account (when the server's admin has turned them on). Each one can run out and be stopped.

import { api } from "./api.js";
import { currentServer } from "./server.js";
import { esc, toast } from "./util.js";

const LASTS = [["1", "A day"], ["7", "A week"], ["30", "A month"], ["never", "Until I stop it"]];
const KINDS = { track: "song", album: "album", playlist: "playlist" };

const linkFor = (path) => currentServer() + path;

function until(ts) {
  if (!ts) return "Works until you stop it";
  if (ts * 1000 < Date.now()) return "Expired";
  return `Works until ${new Date(ts * 1000).toLocaleDateString(undefined, { day: "numeric", month: "long" })}`;
}

async function copy(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch { return false; }
}

function open(html) {
  const d = document.createElement("dialog");
  d.className = "dialog share-dialog";
  d.innerHTML = `<form method="dialog">${html}</form>`;
  document.body.append(d);
  d.addEventListener("close", () => d.remove());
  d.querySelector('[value="cancel"]')?.addEventListener("click", () => d.close());
  d.showModal();
  return d;
}

/** Make a link for a song, album or playlist, then show it to copy or send. */
export function shareLink(kind, id, title) {
  const d = open(`
    <h2>Share “${esc(title)}”</h2>
    <p>Anyone with the link can listen to this ${KINDS[kind]} in their browser, without an account. Nothing else on the server opens to them.</p>
    <label class="field"><span>The link works for</span>
      <select class="select" name="days">${LASTS.map(([v, t]) => `<option value="${v}"${v === "7" ? " selected" : ""}>${t}</option>`).join("")}</select></label>
    <p class="dialog-error" role="alert"></p>
    <div class="dialog-actions">
      <button class="btn" type="button" value="cancel">Cancel</button>
      <button class="btn btn-primary" type="submit">Make link</button>
    </div>`);
  const form = d.querySelector("form");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const v = form.elements.days.value;
    const btn = form.querySelector('[type="submit"]');
    btn.disabled = true;
    try {
      const s = await api.makeShare(kind, id, v === "never" ? null : Number(v));
      d.close();
      showLink(s);
    } catch (err) {
      form.querySelector(".dialog-error").textContent = err.message;
      btn.disabled = false;
    }
  });
}

function showLink(s) {
  const url = linkFor(s.path);
  const d = open(`
    <h2>Your link</h2>
    <p>${esc(until(s.expiresAt))}. You can stop it any time in Settings, under Share links.</p>
    <label class="field"><span>Link</span><input name="url" value="${esc(url)}" readonly spellcheck="false"></label>
    <div class="dialog-actions">
      ${navigator.share ? `<button class="btn" type="button" data-share="send">Send…</button>` : ""}
      <button class="btn btn-primary" type="button" data-share="copy">Copy link</button>
      <button class="btn" type="button" value="cancel">Done</button>
    </div>`);
  const input = d.querySelector('[name="url"]');
  input.addEventListener("focus", () => input.select());
  d.querySelector('[data-share="copy"]').addEventListener("click", async () => {
    if (await copy(url)) toast("Link copied"); else { input.focus(); input.select(); toast("Select the link and copy it"); }
  });
  d.querySelector('[data-share="send"]')?.addEventListener("click", () => navigator.share({ title: s.title, url }).catch(() => {}));
}

/** Your links: where they go, how long they work, and Stop. */
export async function manageLinks() {
  const draw = (links) => links.length ? `<ul class="share-list">${links.map((s) => `
      <li><div><b>${esc(s.title)}</b><span>${esc(s.by ? `${s.by}. ` : "")}${esc(until(s.expiresAt))}. Opened ${s.opened === 1 ? "once" : `${s.opened} times`}.</span></div>
        <button class="btn btn-small" type="button" data-copy="${esc(s.path)}">Copy</button>
        <button class="btn btn-small" type="button" data-stop="${esc(s.token)}">Stop</button></li>`).join("")}</ul>`
    : `<p class="people-note">No links yet. Make one from the menu of a song, album or playlist.</p>`;
  let links = await api.myShares();
  const d = open(`<h2>Share links</h2><p>Links you’ve made. Stopping one closes it for everyone who has it.</p>
    <div class="share-body">${draw(links)}</div>
    <div class="dialog-actions"><button class="btn" type="button" value="cancel">Done</button></div>`);
  d.addEventListener("click", async (e) => {
    const c = e.target.closest("[data-copy]"), s = e.target.closest("[data-stop]");
    if (c) toast((await copy(linkFor(c.dataset.copy))) ? "Link copied" : "Couldn’t copy the link");
    if (s) {
      try {
        await api.stopShare(s.dataset.stop);
        links = links.filter((x) => x.token !== s.dataset.stop);
        d.querySelector(".share-body").innerHTML = draw(links);
        toast("Link stopped");
      } catch (err) { toast(err.message); }
    }
  });
}
