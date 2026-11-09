// In the Android app: tell the phone what's playing, for its media notification, lock screen
// and Bluetooth/car displays, and take the commands those send back.
//
// It follows the Connect controller, so when this phone is the remote for another device the
// notification shows (and controls) what's playing there.

import { nativeApp as android } from "./server.js";
import { coverUrl } from "./util.js";

export function mountNative(player) {
  if (!android?.mediaState) return;
  let sent = "";
  let lastPos = 0, lastAt = 0, lastPlaying = false;

  // A downloaded cover is a blob: URL the phone can't open, so it's passed as the image itself.
  const inlined = new Map(); // blob URL -> data URL
  const inline = (url) => {
    if (!url.startsWith("blob:")) return url;
    if (inlined.has(url)) return inlined.get(url);
    inlined.set(url, "");
    fetch(url).then((r) => r.blob()).then((b) => new Promise((res) => {
      const fr = new FileReader();
      fr.onload = () => res(fr.result);
      fr.readAsDataURL(b);
    })).then((data) => { inlined.set(url, data); sent = ""; send(); }).catch(() => {});
    return "";
  };

  const send = () => {
    const t = player.current;
    const state = t ? {
      title: t.title,
      artist: t.artist,
      album: t.album,
      art: t.cover ? inline(new URL(coverUrl(t.albumId, t.cover, 640), location.href).href) : "",
      duration: player.duration || t.duration || 0,
      position: player.position || 0,
      playing: !!player.playing,
      device: player.remoteMode ? (player.activeDevice?.name ?? "another device") : "",
      // The other device's volume: the phone's volume buttons set it.
      volume: player.remoteMode ? Math.round(player.volume * 100) / 100 : 1,
      hasPrev: true,
      hasNext: player.index < player.queue.length - 1 || player.repeat !== "off",
    } : null;
    lastPos = state?.position ?? 0;
    lastAt = performance.now();
    lastPlaying = !!state?.playing;
    const json = JSON.stringify(state);
    // Position moves on its own; only resend when something else changed.
    const key = JSON.stringify(state && { ...state, position: Math.round(state.position) });
    if (key === sent) return;
    sent = key;
    android.mediaState(json);
  };

  for (const type of ["track", "state", "devices"]) player.addEventListener(type, send);
  // The phone moves the seek bar along by itself; resend only when the position jumps (a seek).
  player.addEventListener("time", () => {
    const expected = lastPos + (lastPlaying ? (performance.now() - lastAt) / 1000 : 0);
    if (Math.abs((player.position || 0) - expected) > 2) { sent = ""; send(); }
  });

  window.shelfNative = {
    command(name, arg) {
      switch (name) {
        case "play": if (!player.playing) player.toggle(); break;
        case "pause": player.pause(); break;
        case "toggle": player.toggle(); break;
        case "next": player.next(); break;
        case "prev": player.prev(); break;
        case "seek": player.seek(Number(arg)); break;
        case "volume": // the phone's volume buttons, while this phone is the remote
          if (player.remoteMode) {
            player.setVolume(Math.max(0, Math.min(1, Number(arg))));
            showVolume(player);
          }
          break;
      }
    },
  };
  send();
}

/** A moment's volume bar at the top of the screen, for the volume buttons while the app is open
 * (Android shows its own when it isn't). */
let hud = null, hudTimer = 0;
function showVolume(player) {
  if (document.hidden) return;
  if (!hud) {
    hud = document.createElement("div");
    hud.className = "vol-hud";
    hud.setAttribute("role", "status");
    hud.innerHTML = `<svg aria-hidden="true"><use href="#i-volume"/></svg><span class="vol-hud-text"><b></b><span class="vol-hud-bar"><span></span></span></span><output></output>`;
    document.body.append(hud);
  }
  const v = player.volume;
  hud.querySelector("b").textContent = player.activeDevice?.name ?? "Other device";
  hud.querySelector(".vol-hud-bar > span").style.width = `${v * 100}%`;
  hud.querySelector("output").textContent = `${Math.round(v * 100)}%`;
  hud.querySelector("use").setAttribute("href", v === 0 ? "#i-mute" : "#i-volume");
  hud.classList.add("show");
  clearTimeout(hudTimer);
  hudTimer = setTimeout(() => hud.classList.remove("show"), 1600);
}

/** Signing out: take the notification away. */
export function clearNative() {
  android?.mediaState?.("null");
}
