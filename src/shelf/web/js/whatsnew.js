// "What's new": after an update, once, what's new and what's fixed (from whatsnew.json, one
// entry per release, newest first). A new device skips it; Settings shows it again any time.

import { esc, store } from "./util.js";

// Nothing of Shelf's stored here yet: a new device (or browser), not an update.
const fresh = (() => {
  try { return !Object.keys(localStorage).some((k) => k.startsWith("shelf.")); } catch { return false; }
})();
if (fresh) store.set("freshDevice", true);

const parts = (v) => String(v || "0").split(".").map((n) => parseInt(n, 10) || 0);
function newer(a, b) {
  const x = parts(a), y = parts(b);
  for (let i = 0; i < Math.max(x.length, y.length); i++) if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) > (y[i] || 0);
  return false;
}

/** The releases since `seen`, up to `current` (at most three). */
export function notesSince(all, seen, current) {
  return all.filter((n) => newer(n.version, seen) && !newer(n.version, current)).slice(0, 3);
}

async function notes() {
  try {
    const r = await fetch("whatsnew.json", { cache: "no-cache" });
    return r.ok ? await r.json() : null;
  } catch { return null; }
}

function open(list, admin, heading) {
  const section = (n) => {
    const items = (n.new || []).filter((i) => admin || !i.admin);
    return `
      <section class="wn-release">
        ${list.length > 1 ? `<h3>Shelf ${esc(n.version)}</h3>` : ""}
        ${items.length ? `<h4>New</h4><ul class="wn-new">${items.map((i) => `<li><b>${esc(i.title)}</b><span>${esc(i.text)}</span></li>`).join("")}</ul>` : ""}
        ${n.fixed?.length ? `<h4>Fixed</h4><ul class="wn-fixed">${n.fixed.map((f) => `<li>${esc(f)}</li>`).join("")}</ul>` : ""}
      </section>`;
  };
  const d = document.createElement("dialog");
  d.className = "dialog whatsnew";
  d.innerHTML = `
    <form method="dialog">
      <header class="wn-head"><span class="wn-disc" aria-hidden="true"></span>
        <h2>${esc(heading ?? (list.length > 1 ? "Shelf has been updated" : `What’s new in Shelf ${list[0].version}`))}</h2></header>
      <div class="wn-body">${list.map(section).join("")}</div>
      <div class="dialog-actions"><button class="btn btn-primary" value="ok">Got it</button></div>
    </form>`;
  document.body.append(d);
  d.addEventListener("close", () => d.remove());
  d.showModal();
  d.querySelector(".btn-primary").focus();
}

/** After an update (the server's version is newer than the last one shown here): show what changed, once. */
export async function maybeShowWhatsNew({ version, admin }) {
  if (!version) return;
  const seen = store.get("whatsNewSeen", null);
  if (!seen && store.get("freshDevice", false)) {
    store.set("whatsNewSeen", version);
    store.set("freshDevice", false);
    return;
  }
  if (seen && !newer(version, seen)) return;
  const all = await notes();
  if (!all) return;
  store.set("whatsNewSeen", version);
  const list = seen ? notesSince(all, seen, version) : all.filter((n) => n.version === version);
  if (list.length && !document.querySelector("dialog[open]")) open(list, admin);
}

/** From Settings: the latest releases' notes. */
export async function showWhatsNew({ admin }) {
  const all = await notes();
  if (all?.length) { const list = all.slice(0, 3); open(list, admin, list.length > 1 ? "What’s new" : undefined); }
}
