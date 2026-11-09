// Sleep timer: stop the music after a while, or at the end of the song. The music fades out
// over a few seconds rather than cutting off.

import { openMenu } from "./menu.js";
import { toast } from "./util.js";

const CHOICES = [[5, "5 minutes"], [15, "15 minutes"], [30, "30 minutes"], [45, "45 minutes"], [60, "1 hour"], [90, "1 hour 30 minutes"]];
const FADE_MS = 8000;

export function mountSleep(player, local) {
  let endsAt = 0;
  let endOfSong = false;
  let timer = 0;
  let tick = 0;

  const buttons = () => document.querySelectorAll(".sleep-btn");
  const draw = () => {
    const on = !!endsAt || endOfSong;
    const left = endsAt ? Math.max(1, Math.round((endsAt - Date.now()) / 60000)) : 0;
    const label = endOfSong ? "Sleep timer: end of this song" : endsAt ? `Sleep timer: ${left} min left` : "Sleep timer";
    for (const b of buttons()) {
      b.classList.toggle("on", on);
      b.setAttribute("aria-label", label);
      b.title = label;
      const badge = b.querySelector(".sleep-left");
      if (badge) badge.textContent = endsAt ? `${left}` : endOfSong ? "♪" : "";
    }
  };

  const cancel = (quiet = false) => {
    clearTimeout(timer);
    clearInterval(tick);
    endsAt = 0;
    endOfSong = false;
    draw();
    if (!quiet) toast("Sleep timer off");
  };

  /** Fade out (when playing here), pause, then put the volume back for next time. */
  const stop = async () => {
    if (!player.remoteMode && player.playing) {
      const start = performance.now();
      // Timers rather than animation frames, which stop while the screen is off.
      await new Promise((resolve) => {
        const t = setInterval(() => {
          const u = (performance.now() - start) / FADE_MS;
          if (u >= 1 || !player.playing) { clearInterval(t); resolve(); return; }
          local.duck(1 - u);
        }, 50);
      });
    }
    player.pause();
    local.duck(1);
    cancel(true);
    toast("Sleep timer: music stopped");
  };

  const set = (minutes) => {
    cancel(true);
    if (minutes === "song") {
      endOfSong = true;
      toast("Music stops at the end of this song");
    } else {
      endsAt = Date.now() + minutes * 60000;
      timer = setTimeout(stop, Math.max(0, minutes * 60000 - FADE_MS));
      tick = setInterval(draw, 30000);
      toast(`Music stops in ${CHOICES.find((c) => c[0] === minutes)[1]}`);
    }
    draw();
  };

  // "End of song": when the next one starts, stop it straight away.
  player.addEventListener("track", () => {
    if (endOfSong) { player.pause(); cancel(true); toast("Sleep timer: music stopped"); }
  });

  document.addEventListener("click", (e) => {
    const b = e.target.closest(".sleep-btn");
    if (!b) return;
    openMenu({
      at: b,
      heading: "Stop the music",
      items: [
        ...CHOICES.map(([m, label]) => ({ label, icon: "i-moon", run: () => set(m) })),
        { label: "End of this song", icon: "i-moon", current: endOfSong, run: () => set("song") },
        ...(endsAt || endOfSong ? ["sep", { label: "Turn off the sleep timer", icon: "i-close", run: () => cancel() }] : []),
      ],
      note: endsAt ? `Stops in about ${Math.round((endsAt - Date.now()) / 60000)} minutes` : null,
    });
  });
  draw();
}
