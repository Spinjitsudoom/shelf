// Reordering the playing queue: each song still to come has a grip. Drag it (mouse or finger)
// and the songs around it make room; let go and the song moves there. With the keyboard, the
// grip moves its song up or down one place with the arrow keys. The playing song and the ones
// already played stay put, as on the phone (player.moveItem keeps to the songs to come).

import { esc } from "./util.js";

let active = false;

/** True while a song is being dragged: lists showing the queue wait before redrawing. */
export const queueDragging = () => active;

/** The grip for queue position `qi`, for a row's actions. */
export const gripHtml = (t, qi) => `
  <button class="icon-btn q-grip" type="button" data-queue-index="${qi}"
    aria-label="Move ${esc(t.title)}: drag it, or use the up and down arrow keys" title="Drag to move"><svg><use href="#i-grip"/></svg></button>`;

/**
 * Lets the grips inside `root` reorder `player`'s queue. `scroller` is the element that scrolls
 * (it scrolls along when a song is dragged near its top or bottom); `redraw` draws the list again.
 */
export function attachQueueDrag(root, player, { scroller = root, redraw = () => {} } = {}) {
  let drag = null;

  root.addEventListener("pointerdown", (e) => {
    const grip = e.target.closest?.(".q-grip");
    if (!grip || e.button !== 0 || active) return;
    const from = Number(grip.dataset.queueIndex);
    const row = grip.closest(".track-row[data-queue-index]");
    if (!row || !(from > player.index)) return;
    e.preventDefault();
    grip.setPointerCapture(e.pointerId);
    const scroll0 = scroller.scrollTop;
    // Where every song still to come sits, in the scrolled content's own coordinates.
    const rows = [...root.querySelectorAll(".track-row[data-queue-index]")]
      .filter((r) => Number(r.dataset.queueIndex) > player.index)
      .map((r) => { const b = r.getBoundingClientRect(); return { el: r, qi: Number(r.dataset.queueIndex), mid: b.top + scroll0 + b.height / 2 }; });
    const me = rows.find((r) => r.el === row);
    const box = row.getBoundingClientRect();
    drag = {
      pointer: e.pointerId, grip, row, from, to: from, rows, trackId: player.queue[from]?.id,
      startY: e.clientY, y: e.clientY, scroll0, mid: me.mid, step: box.height + (parseFloat(getComputedStyle(row.parentElement).rowGap) || 0),
      raf: 0,
    };
    active = true;
    row.classList.add("q-lifted");
    document.body.classList.add("q-dragging");
    tick();
  });

  function layout() {
    const dy = drag.y - drag.startY + (scroller.scrollTop - drag.scroll0);
    const mid = drag.mid + dy;
    let to = drag.from;
    for (const r of drag.rows) {
      if (r.el === drag.row) continue;
      let shift = 0;
      if (r.qi > drag.from && mid > r.mid) { shift = -drag.step; to++; }
      else if (r.qi < drag.from && mid < r.mid) { shift = drag.step; to--; }
      r.el.style.transform = shift ? `translateY(${shift}px)` : "";
    }
    drag.row.style.transform = `translateY(${dy}px)`;
    drag.to = to;
  }

  // Keep laying out each frame, and scroll along near the edges.
  function tick() {
    if (!drag) return;
    const b = scroller.getBoundingClientRect();
    const top = Math.max(b.top, 0), bottom = Math.min(b.bottom, innerHeight);
    const edge = 48;
    const speed = drag.y < top + edge ? -(top + edge - drag.y) : drag.y > bottom - edge ? drag.y - (bottom - edge) : 0;
    if (speed) scroller.scrollTop += Math.max(-18, Math.min(18, speed / 3));
    layout();
    drag.raf = requestAnimationFrame(tick);
  }

  root.addEventListener("pointermove", (e) => {
    if (!drag || e.pointerId !== drag.pointer) return;
    drag.y = e.clientY;
  });

  function finish(e, keep) {
    if (!drag || e.pointerId !== drag.pointer) return;
    const d = drag;
    drag = null;
    cancelAnimationFrame(d.raf);
    for (const r of d.rows) r.el.style.transform = "";
    d.row.classList.remove("q-lifted");
    document.body.classList.remove("q-dragging");
    active = false;
    // Only if the queue is still the one the drag started on (a song may have ended meanwhile).
    if (keep && d.to !== d.from && player.queue[d.from]?.id === d.trackId) player.moveItem(d.from, d.to);
    redraw();
  }
  root.addEventListener("pointerup", (e) => finish(e, true));
  root.addEventListener("pointercancel", (e) => finish(e, false));

  // The grip is a handle, not a song: clicking it doesn't play anything.
  root.addEventListener("click", (e) => { if (e.target.closest?.(".q-grip")) e.stopPropagation(); }, true);

  root.addEventListener("keydown", (e) => {
    const grip = e.target.closest?.(".q-grip");
    if (!grip) return;
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.stopPropagation(); return; }
    if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
    e.preventDefault();
    e.stopPropagation();
    const from = Number(grip.dataset.queueIndex);
    const to = from + (e.key === "ArrowUp" ? -1 : 1);
    if (to <= player.index || to >= player.queue.length) return;
    player.moveItem(from, to);
    // The list is drawn again (sometimes twice): keep the focus on the song that moved.
    const refocus = () => root.querySelector(`.q-grip[data-queue-index="${to}"]`)?.focus();
    setTimeout(refocus, 0);
    setTimeout(refocus, 180);
  }, true);
}
