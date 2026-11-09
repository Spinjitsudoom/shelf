// DJ: your music as a radio show.
//
// The server picks short themed sets and writes and speaks what the host says (see dj.py);
// this plays it the way radio does:
// - Breaks between sets back-announce what just played and set up the next set, after a
//   short jingle. Every couple of songs inside a set there's a quick link too.
// - The host talks up to the "post": what's said is timed to end as the next song's vocals
//   come in. If there's more to say than the intro allows, the host starts over the end of
//   the song before, and the next one comes in underneath.
// - The music is ducked under the voice, and what's said shows as a caption.
// - The next set is fetched before this one runs out, so the show keeps going.

import { api } from "./api.js";
import { toast } from "./util.js";

const DUCK = 0.25; // the music's level under the voice
const RAMP_MS = 450;
const STING_LEAD = 1.1; // seconds of jingle before the voice
const MAX_OVERLAP = 14; // talk over at most this much of the end of a song

export function mountDJ(player, local) {
  let on = false;
  let fetching = null;
  const talks = new Map(); // track id -> what's said before it {text, voice, post, sting, lead, started}
  const starts = new Set(); // first track of each set
  const voice = new Audio();
  const sting = new Audio("sounds/sting.m4a");
  voice.preload = sting.preload = "auto";
  const caption = document.getElementById("dj-caption");
  let level = 1;
  let timer = 0;
  let take = 0;

  // Timers, not animation frames: those stop when the screen is off.
  const ramp = (to, ms = RAMP_MS) => {
    clearInterval(timer);
    const from = level;
    const t0 = performance.now();
    const step = () => {
      const u = Math.min(1, (performance.now() - t0) / ms);
      level = from + (to - from) * u;
      local.duck(level);
      if (u >= 1) clearInterval(timer);
    };
    step();
    timer = setInterval(step, 30);
  };

  let shown = null; // the talk on the caption, for thumbs up or down
  const showCaption = (t) => {
    if (!caption) return;
    shown = t;
    caption.querySelector(".dj-caption-text").textContent = t.text;
    caption.querySelectorAll("[data-dj-rate]").forEach((b) => b.setAttribute("aria-pressed", "false"));
    caption.hidden = false;
  };
  const hideCaption = () => { if (caption) caption.hidden = true; };

  const done = () => {
    ramp(1, 900);
    document.body.classList.remove("dj-talking");
    hideCaption();
  };
  voice.addEventListener("ended", done);
  voice.addEventListener("error", done);

  /** Say a line: duck, jingle (for a proper break), then the voice. */
  const say = (t) => {
    if (!t?.voice?.url || player.remoteMode || t.started) return;
    t.started = true;
    const mine = ++take;
    voice.volume = sting.volume = Math.min(1, local.userVolume); // the host follows the volume setting
    ramp(DUCK);
    document.body.classList.add("dj-talking");
    showCaption(t);
    const go = () => {
      if (mine !== take) return;
      voice.src = t.voice.url;
      voice.play().catch(() => { if (mine === take) done(); });
    };
    if (t.sting) {
      sting.currentTime = 0;
      sting.play().catch(() => {});
      setTimeout(go, STING_LEAD * 1000);
    } else {
      go();
    }
  };

  /** How long before the song ends to start talking (0: wait for the song, then hit the post). */
  const leadOf = (t) => {
    const total = t.voice ? t.voice.seconds + (t.sting ? STING_LEAD : 0) : 0;
    return Math.min(MAX_OVERLAP, Math.max(0, total - t.post + 0.4));
  };

  const remember = (t) => {
    if (t?.theme && t.kind !== "link") themes.set(t.next, t.theme);
    if (!t?.voice) return null;
    t.lead = leadOf(t);
    talks.set(t.next, t);
    return t;
  };

  const clock = () => {
    const d = new Date();
    return { when: d.toLocaleString("en-US", { weekday: "long" }), hour: d.getHours(), minute: d.getMinutes() };
  };

  const setOn = (v) => {
    on = v;
    document.body.classList.toggle("dj-on", v);
    if (!v) {
      take++;
      voice.pause();
      sting.pause();
      done();
      talks.clear();
      starts.clear();
    }
  };

  const seenIds = () => [...new Set(player.queue.map((t) => t.id))];

  /** The next set, once (concurrent calls share the request), with the break before it. */
  const nextSet = () => {
    const last = player.queue[player.queue.length - 1];
    fetching ??= api.djNext({ exclude: seenIds(), previous: last?.id ?? null, ...clock() })
      .then((set) => {
        starts.add(set.tracks[0].id);
        for (const t of set.talks ?? [set]) remember(t); // the break and the set's links, all at once
        return set;
      })
      .finally(() => { fetching = null; });
    return fetching;
  };

  async function start() {
    if (player.remoteMode) {
      toast("Start the DJ on the device that’s playing, or move playback to this one first");
      return;
    }
    toast("Shelf Radio is warming up…", 2500);
    setOn(false);
    preparedAt = 0; // the one made ahead is used now; make another next time
    const set = await api.djNext({ first: true, ...clock() });
    setOn(true);
    starts.add(set.tracks[0].id);
    const talks = (set.talks ?? [set]).map(remember);
    const t = talks[0];
    // mix: songs inside a set blend into each other (the server marks a clean cut before each talk).
    player.playList(set.tracks, 0, { context: { label: "Shelf Radio", href: "#/", dj: true, mix: true } });
    player.enableEngineIfNeeded?.();
    // The opening: jingle and hello straight away, over the first song's intro.
    if (t) say(t);
  }

  /** "Switch it up": straight on to a new set (and the DJ notes this set didn't land). */
  async function skip() {
    if (!on) return start();
    api.djFeedback({ kind: "switch", theme: currentTheme(), track: player.current?.id ?? null }).catch(() => {});
    jumping = true;
    const set = await nextSet();
    const t = talks.get(set.tracks[0].id);
    if (t) { t.lead = 0; t.sting = true; } // we're jumping: talk over the new song's start
    player.playNext(set.tracks, { quiet: true });
    player.next();
  }

  /** A request ("something chill", "more Slipknot"): the next set follows it. */
  async function request(text) {
    if (!on) await start();
    const cur = player.current;
    const set = await api.djRequest({ text, previous: cur?.id ?? null, exclude: seenIds(), ...clock() });
    starts.add(set.tracks[0].id);
    for (const t of set.talks ?? [set]) remember(t);
    const first = talks.get(set.tracks[0].id);
    if (first) { first.lead = 0; first.sting = true; }
    jumping = true;
    player.playNext(set.tracks, { quiet: true });
    player.next();
    return set;
  }

  // Which theme is playing: the theme of the last set that started at or before this song.
  const themes = new Map(); // first track id -> theme
  const currentTheme = () => {
    let theme = null;
    for (let i = 0; i <= player.index; i++) {
      const th = themes.get(player.queue[i]?.id);
      if (th) theme = th;
    }
    return theme;
  };

  // Skips: a song left early (not by the DJ itself) counts against it.
  let jumping = false;
  let lastPos = 0, lastDur = 0, lastId = null;

  /** Two songs from the end of what's queued: get the next set (and all its talk) ready. */
  const plan = () => {
    if (player.index >= player.queue.length - 2) nextSet().then((s) => player.addToQueue(s.tracks, { quiet: true })).catch(() => {});
  };

  player.addEventListener("track", () => {
    if (!on) return;
    if (!player.context?.dj) { setOn(false); return; } // something else is playing now
    if (lastId && !jumping && lastDur > 60 && lastPos > 1 && lastPos < Math.min(lastDur - 15, 45)) {
      api.djFeedback({ kind: "skip", track: lastId, theme: currentTheme() }).catch(() => {});
    }
    jumping = false;
    const cur = player.current;
    lastId = cur?.id ?? null;
    lastPos = 0;
    // A line meant to start over the last song's end that didn't get the chance (it arrived
    // late, or the song was skipped): say it now if we're still in the intro.
    const t = cur && talks.get(cur.id);
    if (t && !t.started && t.voice && t.lead > 0) t.lead = 0;
    plan();
  });

  // The timing: talk over the end of this song into the next, or wait and hit the post.
  player.addEventListener("time", () => {
    if (!on || player.remoteMode || !player.playing) return;
    lastPos = player.position || 0;
    lastDur = player.duration || 0;
    const cur = player.current;
    const nxt = player.queue[player.index + 1];
    const left = (player.duration || 0) - (player.position || 0);
    const tn = nxt && talks.get(nxt.id);
    if (tn?.voice && !tn.started && tn.lead > 0 && left > 0 && left <= tn.lead) say(tn);
    const tc = cur && talks.get(cur.id);
    if (tc?.voice && !tc.started && tc.lead === 0) {
      const total = tc.voice.seconds + (tc.sting ? STING_LEAD : 0);
      const at = Math.max(0, tc.post - total - 0.3);
      if (player.position >= at && player.position < tc.post + 3) say(tc);
      else if (player.position >= tc.post + 3) tc.started = true; // missed it: let the song play
    }
  });

  // Pausing the music pauses the host too (but not the moment a new song is still loading).
  // Only a real pause counts: between songs the player is "not playing" for a moment.
  let wasPlaying = false;
  let pauseCheck = 0;
  player.addEventListener("state", () => {
    const playing = player.playing;
    if (on && wasPlaying && !playing && (!voice.paused || !sting.paused)) {
      clearTimeout(pauseCheck);
      pauseCheck = setTimeout(() => {
        if (player.playing) return;
        take++;
        voice.pause();
        sting.pause();
        done();
      }, 600);
    }
    wasPlaying = playing;
  });

  document.addEventListener("click", (e) => {
    const rate = e.target.closest("[data-dj-rate]");
    if (rate && shown) {
      api.djFeedback({ kind: rate.dataset.djRate, text: shown.text, theme: shown.theme ?? null, track: shown.next ?? null }).catch(() => {});
      caption.querySelectorAll("[data-dj-rate]").forEach((b) => b.setAttribute("aria-pressed", String(b === rate)));
      toast(rate.dataset.djRate === "up" ? "Glad you liked it. The DJ will lean that way." : "Noted. The DJ will try something different.");
      return;
    }
    if (e.target.closest("[data-dj-request]")) { askRequest(); return; }
    const b = e.target.closest("[data-dj]");
    if (!b) return;
    e.preventDefault();
    (b.dataset.dj === "skip" ? skip() : start()).catch((err) => toast(err.message));
  });

  /** The request box: type it, or say it where the browser can listen. */
  function askRequest() {
    const d = document.createElement("dialog");
    d.className = "dialog dj-request";
    const Speech = window.SpeechRecognition || window.webkitSpeechRecognition;
    d.innerHTML = `
      <form method="dialog">
        <h2>Request something</h2>
        <p>An artist from your shelf, a mood (“something chill”, “turn it up”), or “something I’ve never heard”.</p>
        <div class="dj-request-row">
          <input name="text" placeholder="More Slipknot" maxlength="200" autocomplete="off" required>
          ${Speech ? `<button class="icon-btn" type="button" data-listen aria-label="Say it"><svg><use href="#i-mic"/></svg></button>` : ""}
        </div>
        <p class="dialog-error" role="alert"></p>
        <div class="dialog-actions">
          <button class="btn" type="button" value="cancel">Cancel</button>
          <button class="btn btn-primary" type="submit">Request</button>
        </div>
      </form>`;
    document.body.append(d);
    const form = d.querySelector("form");
    const input = form.elements.text;
    d.querySelector('[value="cancel"]').addEventListener("click", () => d.close());
    d.addEventListener("close", () => d.remove());
    d.querySelector("[data-listen]")?.addEventListener("click", (e) => {
      const rec = new Speech();
      rec.lang = navigator.language || "en-US";
      rec.interimResults = false;
      e.currentTarget.classList.add("listening");
      rec.onresult = (ev) => { input.value = ev.results[0][0].transcript; form.requestSubmit(); };
      rec.onend = () => d.querySelector("[data-listen]")?.classList.remove("listening");
      rec.onerror = () => { d.querySelector(".dialog-error").textContent = "Couldn’t hear that. Try typing it."; };
      rec.start();
    });
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      const btn = form.querySelector('[type="submit"]');
      btn.disabled = true;
      btn.textContent = "Asking the DJ…";
      try {
        await request(text);
        d.close();
      } catch (err) {
        d.querySelector(".dialog-error").textContent = err.message;
        btn.disabled = false;
        btn.textContent = "Request";
      }
    });
    d.showModal();
    input.focus();
  }

  /** Have the opening made ahead (from Home), so pressing DJ starts at once. */
  let preparedAt = 0;
  function prepare() {
    if (on || Date.now() - preparedAt < 10 * 60_000) return;
    preparedAt = Date.now();
    const d = new Date();
    const part = d.getHours() < 5 ? "night" : d.getHours() < 12 ? "morning" : d.getHours() < 17 ? "afternoon" : d.getHours() < 22 ? "evening" : "night";
    api.djPrepare({ when: `${d.toLocaleString("en-US", { weekday: "long" })} ${part}`, hour: d.getHours() }).catch(() => {});
  }

  const handle = { start, skip, request, prepare, voice, talks, get on() { return on; }, get level() { return level; } };
  if (window.shelfDebug) window.shelfDebug.dj = handle;
  return handle;
}
