// Lyrics that follow the song: the line being sung is lit, the view keeps it in sight,
// and tapping a line jumps there. Used by the Lyrics page and inside Now Playing.

import { api } from "./api.js";
import { esc } from "./util.js";

const LEAD = 0.25; // light a line slightly before it's sung, as it reads more naturally
const HOLD_AFTER_SCROLL = 4000; // after you scroll yourself, wait this long before following again

function lineAt(lines, t) {
  let lo = 0, hi = lines.length - 1, found = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (lines[mid].t <= t) { found = mid; lo = mid + 1; } else hi = mid - 1;
  }
  return found;
}

function emptyHtml(title, text) {
  return `<div class="ly-empty"><strong>${esc(title)}</strong>${text ? `<span>${esc(text)}</span>` : ""}</div>`;
}

const SOURCE = { lrclib: "Lyrics from LRCLIB", file: "Lyrics from your music file" };

/**
 * Show lyrics for whatever `player` is playing inside `root`, scrolling `scroller`.
 * Returns a cleanup function.
 */
export function mountLyrics(root, scroller, player) {
  let trackId = null, data = null, lines = [], nodes = [], current = -2;
  let heldUntil = 0, programmatic = false, token = 0;

  async function load() {
    const t = player.current;
    if (!t) {
      trackId = null;
      root.innerHTML = emptyHtml("Nothing playing", "Play a song to see its lyrics here.");
      return;
    }
    if (t.id === trackId) return;
    trackId = t.id;
    const mine = ++token;
    root.innerHTML = `<div class="ly-empty ly-loading"><span>Finding lyrics…</span></div>`;
    try {
      data = await api.lyrics(t.id);
    } catch {
      data = null;
    }
    if (mine !== token) return;
    render(t);
    // Have the next song's lyrics ready too.
    const nxt = player.nextTrack;
    if (nxt) api.lyrics(nxt.id).catch(() => {});
  }

  function render(t) {
    current = -2;
    lines = [];
    nodes = [];
    if (!data) {
      root.innerHTML = emptyHtml("Couldn’t load lyrics", "Check that the server is reachable, then try again.");
      return;
    }
    if (data.kind === "instrumental") {
      root.innerHTML = emptyHtml("Instrumental", "No words on this one. Enjoy the music.");
      return;
    }
    if (data.kind === "none") {
      root.innerHTML = emptyHtml(`No lyrics for “${t.title}”`, data.searchedOnline
        ? "They aren’t in the music file, and LRCLIB doesn’t have them either. A .lrc file next to the song works too."
        : "They aren’t in the music file. Add a .lrc file next to the song to see them here.");
      return;
    }
    const credit = `<p class="ly-credit">${SOURCE[data.source] ?? ""}</p>`;
    if (data.kind === "plain") {
      root.innerHTML = `
        <p class="ly-note">These lyrics aren’t timed to the song.</p>
        <div class="ly-plain">${data.text.split(/\n{2,}/).map((verse) => `<p>${esc(verse).replace(/\n/g, "<br>")}</p>`).join("")}</div>
        ${credit}`;
      return;
    }
    lines = data.lines;
    root.innerHTML = `
      <div class="ly-lines">
        ${lines.map((l, i) => `<button class="ly-line${l.text ? "" : " ly-gap"}" type="button" data-i="${i}">${l.text ? esc(l.text) : '<span class="ly-dots" aria-label="Instrumental"><i></i><i></i><i></i></span>'}</button>`).join("")}
      </div>
      ${credit}`;
    nodes = [...root.querySelectorAll(".ly-line")];
    tick(true);
  }

  function tick(jump = false) {
    if (!lines.length) return;
    const i = lineAt(lines, player.position + LEAD);
    if (i === current && !jump) return;
    const prev = current;
    current = i;
    nodes.forEach((n, k) => {
      n.classList.toggle("past", k < i);
      n.classList.toggle("now", k === i);
    });
    if (Date.now() < heldUntil) return;
    // Keep the sung line about a third of the way down.
    const target = nodes[Math.max(0, i)];
    if (!target) return;
    const sr = scroller.getBoundingClientRect();
    const tr = target.getBoundingClientRect();
    const top = scroller.scrollTop + (tr.top - sr.top) - sr.height * 0.33 + tr.height / 2;
    programmatic = true;
    const far = Math.abs(i - prev) > 3;
    scroller.scrollTo({ top: Math.max(0, top), behavior: jump || far ? "auto" : "smooth" });
    clearTimeout(tick.t);
    tick.t = setTimeout(() => { programmatic = false; }, 700);
  }

  const onUserScroll = () => { if (!programmatic) heldUntil = Date.now() + HOLD_AFTER_SCROLL; };
  const onPointer = () => { programmatic = false; heldUntil = Date.now() + HOLD_AFTER_SCROLL; };
  const onClick = (e) => {
    const line = e.target.closest(".ly-line");
    if (!line) return;
    heldUntil = 0;
    player.seek(lines[Number(line.dataset.i)].t);
    if (!player.playing) player.toggle();
  };
  const onTime = () => tick();
  const onTrack = () => load();

  scroller.addEventListener("wheel", onPointer, { passive: true });
  scroller.addEventListener("touchmove", onPointer, { passive: true });
  scroller.addEventListener("scroll", onUserScroll, { passive: true });
  root.addEventListener("click", onClick);
  player.addEventListener("time", onTime);
  player.addEventListener("track", onTrack);
  // Re-center when the panel is first shown or resized.
  const ro = new ResizeObserver(() => { if (scroller.clientHeight) tick(true); });
  ro.observe(scroller);
  load();

  return () => {
    token++;
    ro.disconnect();
    clearTimeout(tick.t);
    scroller.removeEventListener("wheel", onPointer);
    scroller.removeEventListener("touchmove", onPointer);
    scroller.removeEventListener("scroll", onUserScroll);
    root.removeEventListener("click", onClick);
    player.removeEventListener("time", onTime);
    player.removeEventListener("track", onTrack);
  };
}
