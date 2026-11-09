// Quick-actions menu: a small popover at the pointer on desktop, a bottom sheet on phones.

import { esc } from "./util.js";

const layer = document.getElementById("menu-layer");
let opener = null;
let onClose = null;

export const menuOpen = () => !layer.hidden;

/**
 * items: [{ label, icon, run, sub?, current? }] with "sep" between groups.
 * heading: a title shown above the items everywhere; note: a line of help below them.
 * at: { x, y } in viewport pixels, or an element to anchor beside.
 * header: { art, title, sub } shown at the top of the phone sheet.
 * footer: HTML for the bottom of the menu (the device picker's volume), wired up by onMount(menu).
 */
export function openMenu({ items, at, header, heading, note, footer, onMount }) {
  closeMenu();
  opener = document.activeElement;
  const sheet = matchMedia("(max-width: 760px), (pointer: coarse)").matches;
  layer.innerHTML = `
    <div class="menu${sheet ? " menu-sheet" : ""}" role="menu" aria-label="${esc(header?.title ?? "Options")}">
      ${heading ? `<h2 class="menu-heading">${esc(heading)}</h2>` : ""}
      ${!heading && sheet && header ? `<div class="menu-head">${header.art ?? ""}<span><b>${esc(header.title)}</b><span>${esc(header.sub ?? "")}</span></span></div>` : ""}
      ${items.map((it, i) => it === "sep" ? `<div class="menu-sep" role="separator"></div>` : `
        <button class="menu-item${it.sub ? " two-line" : ""}${it.current ? " current" : ""}" type="button" role="menuitem" data-i="${i}"${it.current ? ' aria-current="true"' : ""}>
          <svg aria-hidden="true"><use href="#${it.icon}"/></svg>${it.sub ? `<span class="menu-text"><span>${esc(it.label)}</span><small>${esc(it.sub)}</small></span>` : `<span>${esc(it.label)}</span>`}
        </button>`).join("")}
      ${note ? `<p class="menu-note">${esc(note)}</p>` : ""}
      ${footer ?? ""}
    </div>`;
  layer.hidden = false;
  layer.classList.toggle("dim", sheet);
  const menu = layer.firstElementChild;

  if (!sheet) {
    const r = menu.getBoundingClientRect();
    let x, y;
    if (at instanceof Element) {
      const a = at.getBoundingClientRect();
      x = a.right - r.width;
      y = a.bottom + 4;
      if (y + r.height > innerHeight - 8) y = a.top - r.height - 4;
    } else {
      x = at.x;
      y = at.y;
    }
    menu.style.left = `${Math.max(8, Math.min(x, innerWidth - r.width - 8))}px`;
    menu.style.top = `${Math.max(8, Math.min(y, innerHeight - r.height - 8))}px`;
  }

  menu.addEventListener("click", (e) => {
    const btn = e.target.closest(".menu-item");
    if (!btn) return;
    const item = items[Number(btn.dataset.i)];
    closeMenu();
    item.run();
  });
  onMount?.(menu);
  menu.addEventListener("keydown", (e) => {
    if (e.target.matches("input") && e.key !== "Escape") return; // the slider keeps its own keys
    const buttons = [...menu.querySelectorAll(".menu-item")];
    const i = buttons.indexOf(document.activeElement);
    if (e.key === "ArrowDown") { e.preventDefault(); buttons[(i + 1) % buttons.length].focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); buttons[(i - 1 + buttons.length) % buttons.length].focus(); }
    else if (e.key === "Escape" || e.key === "Tab") { e.preventDefault(); closeMenu(true); }
  });
  menu.querySelector(".menu-item")?.focus({ preventScroll: true });
}

export function closeMenu(restoreFocus = false) {
  if (layer.hidden) return;
  layer.hidden = true;
  layer.innerHTML = "";
  if (restoreFocus && opener?.isConnected) opener.focus({ preventScroll: true });
  opener = null;
  onClose?.();
}

layer.addEventListener("pointerdown", (e) => { if (e.target === layer) closeMenu(); });
layer.addEventListener("contextmenu", (e) => { e.preventDefault(); closeMenu(); });
addEventListener("resize", () => closeMenu());
addEventListener("hashchange", () => closeMenu());
document.addEventListener("scroll", () => closeMenu(), true);
