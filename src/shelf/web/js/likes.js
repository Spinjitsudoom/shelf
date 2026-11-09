// Favourites: the heart on every song. The set of liked songs is loaded once and kept in
// step here; every heart on screen is a button with data-like="<track id>", so a change
// updates them all at once, wherever they are.

import { api } from "./api.js";
import { offline } from "./offline.js";
import { toast } from "./util.js";

let ids = new Set();
let loaded = null;

export const likes = {
  /** Load the liked songs (once; call again with force after another device may have changed them). */
  load(force = false) {
    if (!loaded || force) {
      loaded = api.likedIds()
        .catch(async (e) => {
          // Offline: the liked songs saved with the Favourites download, if there is one.
          if (e.status !== 0) throw e;
          await offline.ready;
          return (offline.data("liked") ?? []).map((t) => t.id);
        })
        .then((list) => { ids = new Set(list); refreshAll(); changed(null); }).catch(() => {});
    }
    return loaded;
  },
  has: (id) => ids.has(Number(id)),
  get count() { return ids.size; },

  async toggle(id, title = "") {
    id = Number(id);
    const on = !ids.has(id);
    // Show it straight away; put it back if the server says no.
    if (on) ids.add(id); else ids.delete(id);
    refreshAll();
    try {
      await (on ? api.like(id) : api.unlike(id));
      toast(on ? "Added to Favourites" : "Removed from Favourites");
      changed(id);
    } catch (e) {
      if (on) ids.delete(id); else ids.add(id);
      refreshAll();
      toast(e.message);
    }
    return on;
  },
};

function changed(id) {
  window.dispatchEvent(new CustomEvent("likes-changed", { detail: { id } }));
}

/** A heart button for a song. */
export function likeButton(t, cls = "") {
  const on = ids.has(t.id);
  return `<button class="like-btn ${cls}" type="button" data-like="${t.id}" aria-pressed="${on}" aria-label="${on ? "Remove from" : "Add to"} Favourites" title="${on ? "Remove from" : "Add to"} Favourites"><svg><use href="#i-heart"/></svg></button>`;
}

/** Bring every heart on screen up to date. */
export function refreshAll(root = document) {
  root.querySelectorAll("[data-like]").forEach((b) => {
    const on = ids.has(Number(b.dataset.like));
    b.setAttribute("aria-pressed", String(on));
    const label = `${on ? "Remove from" : "Add to"} Favourites`;
    b.setAttribute("aria-label", label);
    b.title = label;
  });
}

// Hearts work anywhere: caught before row clicks (which would start playback) see them.
document.addEventListener("click", (e) => {
  const b = e.target.closest?.("[data-like]");
  if (!b || !b.dataset.like) return;
  e.preventDefault();
  e.stopPropagation();
  likes.toggle(b.dataset.like);
}, true);
