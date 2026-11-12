// Admin → Webhooks (see src/shelf/webhooks.py): tell another program, like Home Assistant, when
// a song starts, the music pauses, a listen counts, or new music arrives.

import { api } from "./api.js";
import { esc, toast } from "./util.js";

function when(ts) {
  if (!ts) return "";
  const s = Date.now() / 1000 - ts;
  if (s < 90) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  return h < 24 ? `${h} h ago` : new Date(ts * 1000).toLocaleDateString();
}

function statusText(h) {
  if (!h.lastAt) return "Nothing sent yet.";
  const ok = /^2\d\d$/.test(h.lastStatus || "");
  return ok ? `Last sent ${when(h.lastAt)}: it arrived.`
    : `Last sent ${when(h.lastAt)}: ${/^\d+$/.test(h.lastStatus || "") ? `it answered ${esc(h.lastStatus)}` : esc(h.lastStatus || "it didn’t arrive")}.`;
}

function html(state) {
  const { hooks, events } = state;
  const label = Object.fromEntries(events.map((e) => [e.id, e.label]));
  return `
    <div class="people-head">
      <h2 class="settings-section">Webhooks</h2>
      <button class="btn" type="button" data-hook="add"><svg><use href="#i-plus"/></svg>Add webhook</button>
    </div>
    <p class="people-note">Tell another program when something happens. For Home Assistant, make an automation with a Webhook trigger and paste its address here. Listening is yours only: nobody else’s leaves the server.</p>
    ${hooks.length ? `<ul class="hooks">${hooks.map((h) => `
      <li class="hook">
        <div class="hook-main">
          <span class="hook-url">${esc(h.url)}</span>
          <span class="hook-events">${h.events.map((e) => esc(label[e] || e)).join(", ")}${h.secret ? ", signed" : ""}</span>
          <span class="hook-status${h.lastStatus && !/^2\d\d$/.test(h.lastStatus) ? " bad" : ""}">${statusText(h)}</span>
        </div>
        <div class="hook-actions">
          <button class="btn btn-small" type="button" data-hook="test" data-id="${h.id}">Send a test</button>
          <button class="icon-btn" type="button" data-hook="remove" data-id="${h.id}" aria-label="Remove this webhook" title="Remove"><svg><use href="#i-trash"/></svg></button>
        </div>
      </li>`).join("")}</ul>` : ""}`;
}

function addDialog(events) {
  const d = document.createElement("dialog");
  d.className = "dialog";
  d.innerHTML = `
    <form method="dialog">
      <h2>Add a webhook</h2>
      <label class="field"><span>Address</span>
        <input name="url" type="url" required placeholder="http://homeassistant.local:8123/api/webhook/…" spellcheck="false"></label>
      <fieldset class="hook-pick"><legend>Send a message when</legend>
        ${events.map((e) => `<label><input type="checkbox" name="ev" value="${e.id}"${e.id === "playing" || e.id === "paused" ? " checked" : ""}> ${esc(e.label)}</label>`).join("")}
      </fieldset>
      <label class="field"><span>Secret (optional)</span>
        <input name="secret" autocomplete="off" spellcheck="false">
        <span class="field-hint">Signs each message, so the other program can check it came from this Shelf.</span></label>
      <p class="dialog-error" role="alert"></p>
      <div class="dialog-actions">
        <button class="btn" type="button" value="cancel">Cancel</button>
        <button class="btn btn-primary" type="submit">Add</button>
      </div>
    </form>`;
  document.body.append(d);
  const form = d.querySelector("form");
  return new Promise((resolve) => {
    let result = null;
    d.addEventListener("close", () => { d.remove(); resolve(result); });
    d.querySelector('[value="cancel"]').addEventListener("click", () => d.close());
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const err = d.querySelector(".dialog-error");
      const picked = [...form.querySelectorAll('input[name="ev"]:checked')].map((c) => c.value);
      if (!picked.length) { err.textContent = "Pick at least one."; return; }
      try {
        result = await api.addWebhook({ url: form.elements.url.value.trim(), events: picked, secret: form.elements.secret.value });
        d.close();
      } catch (ex) { err.textContent = ex.message; }
    });
    d.showModal();
    form.elements.url.focus();
  });
}

/** Fills `box` with the Webhooks section, and keeps it up to date. */
export function mountWebhooks(box) {
  let state = null;
  const draw = () => { box.innerHTML = state ? html(state) : ""; };
  const load = () => api.webhooks().then((s) => { state = s; draw(); }).catch(() => { box.innerHTML = ""; });
  box.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-hook]");
    if (!b || !state) return;
    const id = Number(b.dataset.id);
    if (b.dataset.hook === "add") {
      if (await addDialog(state.events)) { toast("Webhook added. Send a test to check it arrives."); load(); }
    } else if (b.dataset.hook === "test") {
      b.disabled = true;
      b.textContent = "Sending…";
      try {
        const r = await api.testWebhook(id);
        toast(/^2\d\d$/.test(r.status) ? "The test arrived" : `The test didn’t arrive: ${r.status}`);
      } catch (ex) { toast(ex.message); }
      load();
    } else if (b.dataset.hook === "remove") {
      await api.removeWebhook(id).catch((ex) => toast(ex.message));
      load();
    }
  });
  load();
}
