// API keys: how newer apps made for Subsonic and Navidrome sign in, with one key instead of a
// username and password. Each key is shown once, when it's made; it can be removed any time.

import { api } from "./api.js";
import { esc, toast } from "./util.js";

const when = (ts) => new Date(ts * 1000).toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" });

function open(html) {
  const d = document.createElement("dialog");
  d.className = "dialog share-dialog";
  d.innerHTML = `<form method="dialog">${html}</form>`;
  document.body.append(d);
  d.addEventListener("close", () => d.remove());
  d.addEventListener("click", (e) => { if (e.target.closest('[value="cancel"]')) d.close(); });
  d.showModal();
  return d;
}

export async function manageKeys() {
  const draw = (keys) => keys.length ? `<ul class="share-list">${keys.map((k) => `
      <li><div><b>${esc(k.name)}</b><span>Ends in …${esc(k.hint)}. Made ${when(k.createdAt)}. ${k.usedAt ? `Last used ${when(k.usedAt)}.` : "Not used yet."}</span></div>
        <button class="btn btn-small" type="button" data-remove="${k.id}">Remove</button></li>`).join("")}</ul>`
    : `<p class="people-note">No keys yet.</p>`;
  let keys = (await api.apiKeys()).keys;
  const d = open(`<h2>API keys</h2>
    <p>Some apps made for Subsonic and Navidrome sign in with a key instead of a username and password. Make one for each app, so you can remove one without signing the others out.</p>
    <label class="field"><span>Name it after the app</span><input name="name" value="" placeholder="Symfonium" maxlength="80" autocomplete="off"></label>
    <div class="key-made"></div>
    <div class="share-body">${draw(keys)}</div>
    <p class="dialog-error" role="alert"></p>
    <div class="dialog-actions">
      <button class="btn" type="button" value="cancel">Done</button>
      <button class="btn btn-primary" type="submit">Make a key</button>
    </div>`);
  const form = d.querySelector("form");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = form.querySelector('[type="submit"]');
    btn.disabled = true;
    try {
      const made = await api.newApiKey(form.elements.name.value.trim() || "App");
      keys = made.keys;
      d.querySelector(".share-body").innerHTML = draw(keys);
      d.querySelector(".key-made").innerHTML = `
        <label class="field"><span>Your new key: copy it now, it won’t be shown again</span>
          <input name="key" value="${esc(made.key)}" readonly spellcheck="false"></label>
        <button class="btn btn-small" type="button" data-copy>Copy key</button>`;
      const input = d.querySelector('[name="key"]');
      input.focus(); input.select();
      form.elements.name.value = "";
      form.querySelector(".dialog-error").textContent = "";
    } catch (err) {
      form.querySelector(".dialog-error").textContent = err.message;
    }
    btn.disabled = false;
  });
  d.addEventListener("click", async (e) => {
    if (e.target.closest("[data-copy]")) {
      const v = d.querySelector('[name="key"]').value;
      try { await navigator.clipboard.writeText(v); toast("Key copied"); } catch { toast("Select the key and copy it"); }
    }
    const r = e.target.closest("[data-remove]");
    if (r) {
      try {
        keys = (await api.removeApiKey(r.dataset.remove)).keys;
        d.querySelector(".share-body").innerHTML = draw(keys);
        toast("Key removed: apps using it are signed out");
      } catch (err) { toast(err.message); }
    }
  });
}
