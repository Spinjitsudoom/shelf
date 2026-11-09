// Music videos: the song's official video plays in
// YouTube's own player (from youtube-nocookie.com), starting where the song was. Shelf's
// audio pauses meanwhile; switching back picks the song up where the video got to.
//
// While a video is on, the player bar's buttons control it (see main.js).

let apiReady = null;

/** Load YouTube's player script once, when the first video is opened. */
function loadYouTube() {
  if (apiReady) return apiReady;
  apiReady = new Promise((resolve, reject) => {
    if (window.YT?.Player) return resolve(window.YT);
    const prev = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = () => { prev?.(); resolve(window.YT); };
    const s = document.createElement("script");
    s.src = "https://www.youtube.com/iframe_api";
    s.onerror = () => { apiReady = null; reject(new Error("Couldn’t reach YouTube")); };
    document.head.append(s);
  });
  return apiReady;
}

export class VideoMode extends EventTarget {
  constructor(local) {
    super();
    this.local = local; // the Player on this device
    this.yt = null;
    this.host = null;
    this.trackId = null;
    this._timer = 0;
  }

  get active() { return !!this.host; } // from the moment a video is opened, while it loads too
  get time() {
    // Until the video has loaded, "where it got to" is where it was asked to start.
    try { return (this.yt?.getCurrentTime ? this.yt.getCurrentTime() : null) ?? this._startAt ?? 0; } catch { return this._startAt ?? 0; }
  }
  get duration() { try { return this.yt?.getDuration() || 0; } catch { return 0; } }
  get playing() { try { return this.yt?.getPlayerState() === 1; } catch { return false; } }

  /** Play `videoId` inside `host`, starting at `startAt` seconds. */
  /** With `related`, it's another video by the artist: when it ends, the song carries on. */
  async start(host, videoId, startAt, trackId, { related = false } = {}) {
    if (this.active) this._teardown();
    this.related = related;
    this.lastVideoId = videoId;
    this.lastError = null;
    this.host = host;
    this.trackId = trackId;
    this._startAt = startAt;
    host.hidden = false;
    host.innerHTML = `<div class="video-frame"><div></div></div>
      <button class="btn video-exit" type="button"><svg><use href="#i-note"/></svg>Switch to audio</button>`;
    host.querySelector(".video-exit").addEventListener("click", () => this.stop(true));
    this._emit("change");
    const wasPlaying = this.local.playing;
    this._wasPlaying = wasPlaying;
    this.local.pause();
    let YT;
    try {
      YT = await loadYouTube();
    } catch (e) {
      this._teardown();
      if (wasPlaying) this.local.play();
      throw e;
    }
    if (this.host !== host) return; // stopped while loading
    this.yt = new YT.Player(host.querySelector(".video-frame > div"), {
      host: "https://www.youtube-nocookie.com",
      videoId,
      playerVars: { autoplay: 1, start: Math.floor(startAt), playsinline: 1, rel: 0, modestbranding: 1 },
      events: {
        onReady: (e) => { e.target.playVideo(); this._emit("change"); },
        onStateChange: (e) => {
          if (e.data === YT.PlayerState.ENDED) {
            const related = this.related;
            this.stop(related);
            if (!related) this._emit("ended");
          }
          else this._emit("change");
        },
        onError: (e) => { this.lastError = e.data; this.stop(true); this._emit("error"); },
      },
    });
    this._timer = setInterval(() => this._emit("time"), 500);
    this._emit("change");
  }

  /** Close the video. With `resume`, the song carries on from the video's position. */
  stop(resume = true) {
    if (!this.host) return;
    const t = this.time;
    const related = this.related;
    this._teardown();
    if (resume) {
      // The song's own video picks the song up where the video got to; another video
      // leaves the song where it was, playing again only if it was playing before.
      if (!related) { this.local.seek(t); this.local.play(); }
      else if (this._wasPlaying) this.local.play();
    }
  }

  _teardown() {
    clearInterval(this._timer);
    try { this.yt?.destroy(); } catch { /* already gone */ }
    this.yt = null;
    if (this.host) { this.host.innerHTML = ""; this.host.hidden = true; }
    this.host = null;
    this.trackId = null;
    this._emit("change");
  }

  toggle() {
    if (!this.yt) return;
    if (this.playing) this.yt.pauseVideo(); else this.yt.playVideo();
  }

  seek(sec) { this.yt?.seekTo(sec, true); }

  _emit(type) { this.dispatchEvent(new Event(type)); }
}
