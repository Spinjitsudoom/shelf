// Admin dashboard: the people who use this server, the library and its folders, and storage.
// Only admins see it (the server checks too).

import { api } from "./api.js";
import { openMenu } from "./menu.js";
import { esc, fallbackColor, fmtListening, plural, toast } from "./util.js";
import { fmtBytes, row } from "./views.js";

const REFRESH_MS = 15_000;

function ago(ts) {
  if (!ts) return null;
  const s = Date.now() / 1000 - ts;
  if (s < 90) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} minutes ago`;
  const h = Math.round(m / 60);
  if (h < 24) return h === 1 ? "an hour ago" : `${h} hours ago`;
  const d = Math.round(h / 24);
  if (d < 30) return d === 1 ? "yesterday" : `${d} days ago`;
  return new Date(ts * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

function initials(name) {
  const parts = name.trim().split(/\s+/);
  return (parts.length > 1 ? parts[0][0] + parts[parts.length - 1][0] : name.slice(0, 2)).toUpperCase();
}

/** Each person is a disc: their initials on the label, in a color of their own. */
const disc = (u) => `
  <span class="person-disc" style="--disc:${fallbackColor(u.username)}" aria-hidden="true"><span>${esc(initials(u.username))}</span></span>`;

function presence(u) {
  if (u.devices) return `<span class="presence on">Online now${u.devices > 1 ? ` on ${u.devices} devices` : ""}</span>`;
  const seen = ago(Math.max(u.lastSeen ?? 0, u.lastPlayed ?? 0));
  return `<span class="presence">${seen ? `Active ${seen}` : "Hasn’t signed in yet"}</span>`;
}

function personRow(u, me) {
  const what = [plural(u.plays, "play"), plural(u.likes, "liked song"), plural(u.playlists, "playlist")].join(", ");
  return `
    <li class="person">
      ${disc(u)}
      <span class="person-text">
        <span class="person-name">${esc(u.username)}${u.admin ? `<span class="tag">Admin</span>` : ""}${u.id === me.id ? `<span class="tag tag-quiet">You</span>` : ""}</span>
        <span class="person-sub">${what}</span>
        ${presence(u)}
      </span>
      <button class="icon-btn" type="button" data-admin="person-menu" data-id="${u.id}" aria-label="Options for ${esc(u.username)}" title="Options"><svg><use href="#i-more"/></svg></button>
    </li>`;
}

function chart(perDay) {
  const max = Math.max(1, ...perDay);
  const day = (i) => {
    const d = new Date(Date.now() - (13 - i) * 86400_000);
    return i === 13 ? "Today" : d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
  };
  return `
    <div class="plays-chart" role="img" aria-label="Songs played each day for the last two weeks">
      ${perDay.map((n, i) => `<span class="bar${n ? "" : " zero"}" style="--h:${(n / max) * 100}%" title="${day(i)}: ${plural(n, "song")}"></span>`).join("")}
    </div>
    <div class="plays-axis"><span>2 weeks ago</span><span>Today</span></div>`;
}

function libraryPart(o, dirs) {
  const scan = o.scan;
  const lib = o.library;
  const scanText = scan.running
    ? `Scanning now${scan.processed ? `, ${scan.processed} files read so far` : ""}…`
    : scan.error ? `Last scan failed: ${esc(scan.error)}`
    : o.lastScan ? `Last checked ${new Date(o.lastScan * 1000).toLocaleString()}` +
        (scan.last ? `. Found ${scan.last.added} new, ${scan.last.updated} changed, ${scan.last.removed} removed${scan.last.failed ? `, ${scan.last.failed} unreadable` : ""}.` : ".")
    : "Not scanned yet.";
  const measuring = [
    o.loudnessMeasured < lib.tracks ? `Measuring loudness: ${o.loudnessMeasured} of ${lib.tracks} songs done.` : "",
    o.rhythmMeasured < lib.tracks ? `Measuring tempo and key: ${o.rhythmMeasured} of ${lib.tracks} songs done.` : "",
    o.soundMeasured < lib.tracks ? `Listening for how songs sound (for “sounds like”): ${o.soundMeasured} of ${lib.tracks} done.` : "",
  ].filter(Boolean).join("<br>");
  const folders = dirs?.folders ?? [];
  return `
    <h2 class="settings-section">Library</h2>
    ${row("Scanning", `${scanText}${measuring ? `<br>${measuring}` : ""}`,
      `<button class="btn" type="button" data-action="rescan" ${scan.running ? "disabled" : ""}>Rescan library</button>`)}
    <div class="folders">
      <div class="folders-head">
        <div><h3 class="row-title-plain">Music folders</h3>
          <p class="folders-sub">${dirs?.locked ? "Set on the server with SHELF_MUSIC_DIRS, so they can’t be changed here."
            : "Shelf looks for music in these folders on the server, and checks them for changes every few minutes."}</p></div>
        <span class="folders-tools">
          ${folders.length ? `<button class="btn btn-primary" type="button" data-admin="upload"><svg><use href="#i-upload"/></svg>Add music</button>` : ""}
          ${dirs?.locked ? "" : `<button class="btn" type="button" data-action="folder-add"><svg><use href="#i-plus"/></svg>Add folder</button>`}
        </span>
      </div>
      ${folders.map((f) => `
        <div class="folder-row${f.available ? "" : " missing"}">
          <svg class="folder-icon" aria-hidden="true"><use href="#i-folder"/></svg>
          <span class="folder-text"><span class="folder-path">${esc(f.path)}</span>
            <span class="folder-sub">${!f.available ? "Not available right now (unplugged or not mounted). Its songs stay in the library until it’s back."
              : f.tracks == null ? "" : plural(f.tracks, "song")}</span></span>
          ${dirs?.locked ? "" : `<span class="folder-actions">
            <button class="btn btn-small" type="button" data-action="folder-change" data-path="${esc(f.path)}">Change</button>
            <button class="icon-btn" type="button" data-action="folder-remove" data-path="${esc(f.path)}" aria-label="Remove ${esc(f.path)}" title="Remove from library"><svg><use href="#i-trash"/></svg></button>
          </span>`}
        </div>`).join("") || `<p class="folders-empty">No music folders yet. Add the folder where your music is.</p>`}
    </div>
    ${row("Watch folder", o.watch?.path
      ? `Music dropped into <b>${esc(o.watch.path)}</b> is renamed from its tags and filed into your first music folder as Artist/Album.`
      : "A folder to drop music into: Shelf renames each song from its tags and files it into your music as Artist/Album, with its cover.",
      `${o.watch?.path ? `<button class="btn btn-small" type="button" data-action="watch-off">Turn off</button>` : ""}
       <button class="btn" type="button" data-action="watch-set">${o.watch?.path ? "Change" : "Choose folder"}</button>`)}

    <div id="health-slot"></div>
    <div id="dj-slot"></div>
    <div id="cd-slot"></div>

    <h2 class="settings-section">Storage</h2>
    ${row("Converted copies", `Smaller copies made for streaming below Lossless: ${fmtBytes(o.storage.transcodeBytes)} of ${fmtBytes(o.storage.transcodeLimitBytes)}. They’re made again when needed.`,
      `<button class="btn" type="button" data-action="clear-storage" ${o.storage.transcodeBytes ? "" : "disabled"}>Clear</button>`)}
    ${row("Cover images", `${fmtBytes(o.storage.coverBytes)} of resized artwork.`, "")}
    ${backupsPart(o.backups)}`;
}

/** Library health: the report, or the button that asks for it. */
function healthHtml(r) {
  const intro = "Albums without covers, gaps in track numbers, the same song twice and files Shelf can’t read. Looking changes nothing.";
  if (!r) {
    return `<h2 class="settings-section">Library health</h2>
      ${row("Check your library", intro, `<button class="btn" type="button" data-admin="health-check">Check library</button>`)}`;
  }
  const c = r.counts;
  const total = Object.values(c).reduce((a, b) => a + b, 0);
  const more = (kind, shown) => c[kind] > shown ? `<li class="health-more">And ${c[kind] - shown} more.</li>` : "";
  const album = (a) => `<b>${esc(a.title)}</b> <span class="health-by">by ${esc(a.artist)}</span>`;
  const coverBtn = (a, label) => `<button class="btn btn-small" type="button" data-admin="cover-choose" data-id="${a.id}" data-title="${esc(a.title)}">${label}</button>`;
  const f = r.finder;
  const finding = f.running ? `Looking for covers: ${f.done} of ${f.total} albums, ${plural(f.found, "cover")} found so far…`
    : f.finishedAt ? `Last look: ${plural(f.found, "cover")} found for ${plural(f.total, "album")}. Albums it didn’t match closely enough can be picked by hand.` : "";
  const kinds = [
    ["noCover", "Albums without a cover", "Shelf can look them up on MusicBrainz. Found covers are kept in Shelf’s data folder; nothing in your music folders changes.",
      r.noCover.map((a) => `<li>${album(a)}${coverBtn(a, "Choose cover")}</li>`).join(""),
      `<button class="btn" type="button" data-admin="covers-find"${f.running ? " disabled" : ""}>Find covers</button>`],
    ["smallCover", "Small covers", "Under 500 pixels across, so they look soft on a big screen.",
      r.smallCover.map((a) => `<li>${album(a)} <span class="health-by">${a.size[0]}×${a.size[1]}</span>${coverBtn(a, "Find a bigger one")}</li>`).join(""), ""],
    ["gaps", "Gaps in track numbers", "Songs that may be missing from these albums (or were never ripped).",
      r.gaps.map((g) => `<li>${album(g)} <span class="health-by">${g.disc > 1 ? `disc ${g.disc}, ` : ""}no track ${esc(g.missing.join(", "))}</span></li>`).join(""), ""],
    ["duplicates", "The same song twice", "The same artist and title, the same length, on different albums. The best copy is marked.",
      r.duplicates.map((d) => `<li><b>${esc(d.title)}</b> <span class="health-by">by ${esc(d.artist)}</span><ul class="health-copies">${d.copies.map((x) =>
        `<li>${esc(x.album)} <span class="health-by">${esc((x.codec || "").toUpperCase())}${x.bitrate ? ` ${Math.round(x.bitrate / 1000)} kbps` : ""}</span>${x.id === d.best ? `<span class="tag">Best copy</span>` : ""}</li>`).join("")}</ul></li>`).join(""), ""],
    ["noArtist", "Songs with no artist", "Their files have no artist tag, so they show as Unknown Artist.",
      r.noArtist.map((t) => `<li><b>${esc(t.title)}</b> <span class="health-path">${esc(t.path)}</span></li>`).join(""), ""],
    ["mixedYears", "Albums with mixed years", "Their songs disagree on the year, often a remaster mixed with the original.",
      r.mixedYears.map((m) => `<li>${album(m)} <span class="health-by">${esc(m.years.join(", "))}</span></li>`).join(""), ""],
    ["unreadable", "Files Shelf can’t read", "Damaged, or in a format Shelf doesn’t know. They’re left out of the library.",
      r.unreadable.map((p) => `<li><span class="health-path">${esc(p)}</span></li>`).join(""), ""],
  ].filter(([k]) => c[k]);
  return `
    <div class="people-head"><h2 class="settings-section">Library health</h2>
      <button class="btn" type="button" data-admin="health-check">Check again</button></div>
    ${finding ? `<p class="people-note">${esc(finding)}</p>` : ""}
    ${total ? kinds.map(([k, title, note, items, action]) => `
      <details class="health" data-kind="${k}">
        <summary><span class="health-count">${c[k].toLocaleString()}</span><span class="health-title">${title}</span>${action}</summary>
        <p class="health-note">${note}</p>
        <ul class="health-list">${items}${more(k, r[k].length)}</ul>
      </details>`).join("") : `<p class="people-note">All clear: every album has a cover, no gaps, no doubles, and every file reads.</p>`}`;
}

/** Pick a cover for an album from what MusicBrainz has. */
async function chooseCover(albumId, title, done) {
  const d = document.createElement("dialog");
  d.className = "dialog cover-dialog";
  d.innerHTML = `<form method="dialog"><h2>A cover for ${esc(title)}</h2>
    <p class="cover-status">Looking on MusicBrainz…</p><div class="cover-grid"></div>
    <div class="dialog-actions"><button class="btn" type="button" data-cover="own">Use the album’s own</button><button class="btn" value="cancel">Close</button></div></form>`;
  document.body.append(d);
  d.addEventListener("close", () => d.remove());
  d.showModal();
  const status = d.querySelector(".cover-status");
  try {
    const found = await api.coverCandidates(albumId);
    status.textContent = found.length ? "Pick the one that’s this album. It’s downloaded at full size." : "MusicBrainz has nothing under that title and artist.";
    d.querySelector(".cover-grid").innerHTML = found.map((c) => `
      <button class="cover-pick" type="button" data-mbid="${esc(c.mbid)}">
        <img src="${esc(c.image)}" alt="" loading="lazy" onerror="this.closest('.cover-pick').hidden = true">
        <span><b>${esc(c.title)}</b>${esc(c.artist)}${c.year ? `, ${c.year}` : ""}${c.type ? ` (${esc(c.type)})` : ""}</span>
      </button>`).join("");
  } catch (err) { status.textContent = err.message; }
  d.addEventListener("click", async (e) => {
    const own = e.target.closest('[data-cover="own"]');
    const pick = e.target.closest(".cover-pick");
    if (!own && !pick) return;
    status.textContent = own ? "Going back to the album’s own cover…" : "Downloading the cover…";
    try {
      if (own) await api.dropFoundCover(albumId); else await api.useCover(albumId, pick.dataset.mbid);
      toast(own ? "Back to the album’s own cover" : `New cover for ${title}`);
      d.close();
      done?.();
    } catch (err) { status.textContent = err.message; }
  });
}

/** Copies of the database: accounts, likes, playlists and play history, which a rescan can't bring back. */
function backupsPart(b) {
  if (!b) return "";
  const when = (ts) => new Date(ts * 1000).toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
  return `
    <div class="folders backups">
      <div class="folders-head">
        <div><h3 class="row-title-plain">Backups</h3>
          <p class="folders-sub">Accounts, Favourites, playlists and play history: what a rescan can’t bring back. Shelf copies them once a day and keeps a week of days and two months of weeks, in <b>${esc(b.folder)}</b>. A folder on another drive is safer.</p></div>
        <span class="folders-tools">
          <button class="btn" type="button" data-action="backup-folder">Change folder</button>
          <button class="btn btn-primary" type="button" data-admin="backup-now">Back up now</button>
        </span>
      </div>
      ${b.backups.map((x) => `
        <div class="folder-row">
          <svg class="folder-icon" aria-hidden="true"><use href="#i-clock"/></svg>
          <span class="folder-text"><span class="folder-path">${esc(when(x.at))}</span>
            <span class="folder-sub">${fmtBytes(x.size)}${x.name.includes("before-restore") ? ", made just before a restore" : ""}</span></span>
          <span class="folder-actions">
            <a class="icon-btn" href="/api/admin/backups/${encodeURIComponent(x.name)}" download aria-label="Download the backup from ${esc(when(x.at))}" title="Download"><svg><use href="#i-download"/></svg></a>
            <button class="btn btn-small" type="button" data-admin="backup-restore" data-name="${esc(x.name)}" data-when="${esc(when(x.at))}">Restore</button>
          </span>
        </div>`).join("") || `<p class="folders-empty">No backups yet. The first one is made a minute after Shelf starts.</p>`}
    </div>`;
}

/** Wrong passwords lately: 8 from one address within 15 minutes locks it out. */
function signinPart(list) {
  const until = (ts) => new Date(ts * 1000).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  const locked = list.filter((x) => x.locked).length;
  return `
    <div class="people-head signin-head">
      <h2 class="settings-section">Sign-in</h2>
      ${list.length > 1 ? `<button class="btn" type="button" data-admin="unlock-all">Clear all</button>` : ""}
    </div>
    <p class="people-note">${list.length
      ? `${locked ? `${locked === 1 ? "One address is" : `${locked} addresses are`} locked out after 8 wrong passwords. ` : ""}Clearing lets them try again straight away.`
      : "No wrong passwords in the last 15 minutes. After 8 from the same address, it’s locked out for 15 minutes; you can lift that here."}</p>
    ${list.length ? `<ul class="people signins">${list.map((x) => `
      <li class="person">
        <span class="signin-icon ${x.locked ? "locked" : ""}" aria-hidden="true"><svg><use href="#${x.locked ? "i-lock" : "i-key"}"/></svg></span>
        <span class="person-text">
          <span class="person-name">${esc(x.address)}</span>
          <span class="person-sub">${plural(x.attempts, "wrong password")} in the last 15 minutes</span>
          <span class="presence ${x.locked ? "locked" : ""}">${x.locked ? `Locked out until ${until(x.until)}` : `${8 - x.attempts} more before it’s locked out`}</span>
        </span>
        <button class="btn btn-small" type="button" data-admin="unlock" data-address="${esc(x.address)}">${x.locked ? "Unlock" : "Clear"}</button>
      </li>`).join("")}</ul>` : ""}`;
}

/** A newer Shelf is out: say so, with the button that updates this server. */
function updatePart(u) {
  if (!u?.available) return "";
  const how = {
    script: "Updating keeps your settings and library, and Shelf restarts by itself.",
    git: "Updating pulls the new code into this folder and restarts Shelf.",
    windows: "Updating installs the new version over this one and starts Shelf Server again.",
    manual: "This copy of Shelf can’t update itself: install the new version the way you installed this one.",
  }[u.kind];
  return `
    <section class="update-banner" aria-live="polite">
      <div>
        <h2>Shelf ${esc(u.latest)} is out</h2>
        <p>This server runs ${esc(u.current)}. ${how}</p>
      </div>
      <div class="update-actions">
        ${u.url ? `<a class="btn" href="${esc(u.url)}" target="_blank" rel="noopener">What’s new</a>` : ""}
        ${u.kind !== "manual" ? `<button class="btn btn-primary" type="button" data-admin="update-now"${u.updating ? " disabled" : ""}>${u.updating ? "Updating…" : "Update now"}</button>` : ""}
      </div>
    </section>`;
}

function page(o, dirs, me) {
  const lib = o.library;
  const week = o.week;
  return `
    <div class="page settings admin">
      <header class="page-head"><h1 class="page-title">Admin</h1></header>
      ${updatePart(o.update)}
      <div class="stats">
        <div class="stat"><b>${lib.tracks.toLocaleString()}</b><span>songs</span></div>
        <div class="stat"><b>${lib.albums}</b><span>albums</span></div>
        <div class="stat"><b>${lib.artists}</b><span>artists</span></div>
        <div class="stat"><b>${Math.round(lib.duration / 3600)}</b><span>hours</span></div>
        <div class="stat"><b>${fmtBytes(lib.bytes)}</b><span>on disk</span></div>
      </div>

      <h2 class="settings-section">Listening</h2>
      <div class="listening">
        <p class="listening-lead">${week.plays
          ? `<b>${plural(week.plays, "song")}</b> played this week, ${fmtListening(week.seconds)} of music, by ${plural(week.people, "person").replace("persons", "people")}.`
          : "Nothing played this week yet."}
          ${o.devices ? ` ${plural(o.devices, "device")} online right now.` : ""}</p>
        ${chart(o.playsPerDay)}
      </div>

      <div class="people-head">
        <h2 class="settings-section">People</h2>
        <button class="btn btn-primary" type="button" data-admin="person-add"><svg><use href="#i-person-add"/></svg>Add person</button>
      </div>
      <p class="people-note">Everyone shares the music. Each person has their own Favourites, playlists, history and devices.</p>
      <ul class="people">${o.users.map((u) => personRow(u, me)).join("")}</ul>

      ${signinPart(o.signins ?? [])}

      ${libraryPart(o, dirs)}

      <h2 class="settings-section">Services</h2>
      ${row("Last.fm", o.lastfm ? "People here can scrobble to Last.fm from Settings." : "Add the server’s Last.fm API account so people here can scrobble to Last.fm.",
        `<button class="btn" type="button" data-admin="lastfm">${o.lastfm ? "Change" : "Set up"}</button>`)}
      ${o.update && o.update.kind !== "manual" ? row("Install updates by themselves", "At night, once nothing has played on any device for half an hour, so music is never cut off.",
        `<button class="switch" type="button" role="switch" data-admin="update-auto" aria-checked="${!!o.update.auto}" aria-label="Install updates by themselves"></button>`) : ""}

      <p class="about">Shelf server ${esc(o.version)}${o.update?.checkedAt && !o.update.available
        ? `, up to date (checked ${esc(ago(o.update.checkedAt))})` : ""}
        <button class="link-btn" type="button" data-admin="update-check">Check for updates</button></p>
    </div>`;
}

export async function adminView(el, session, { dialog }) {
  const me = session.user;
  if (!me?.admin) {
    el.innerHTML = `<div class="page"><div class="empty"><strong>Only admins can open this</strong>Ask the person who runs this server. <a href="#/" style="text-decoration:underline">Go home</a></div></div>`;
    return null;
  }
  let [o, dirs] = await Promise.all([api.adminOverview(), api.folders().catch(() => null)]);
  let shown = "";
  // The CD drive's section lives on across redraws, so a half-edited track list isn't lost.
  const cdBox = document.createElement("section");
  cdBox.className = "cd-box";
  const djBox = document.createElement("section");
  djBox.className = "dj-box";
  // Library health lives on across redraws too: it's only worked out when asked for.
  const healthBox = document.createElement("section");
  healthBox.className = "health-box";
  healthBox.innerHTML = healthHtml(null);
  const draw = () => {
    const html = page(o, dirs, me);
    if (html === shown) return;
    const top = el.scrollTop;
    el.innerHTML = html;
    el.querySelector("#cd-slot")?.replaceWith(cdBox);
    el.querySelector("#dj-slot")?.replaceWith(djBox);
    el.querySelector("#health-slot")?.replaceWith(healthBox);
    el.scrollTop = top;
    shown = html;
  };
  draw();

  const refresh = async () => {
    try {
      [o, dirs] = await Promise.all([api.adminOverview(), api.folders().catch(() => dirs)]);
      draw();
    } catch { /* offline for a moment: try again next time */ }
  };
  // Keep the numbers live, but don't redraw under an open menu or dialog.
  const timer = setInterval(() => {
    if (!document.hidden && !document.querySelector("dialog[open]") && document.getElementById("menu-layer").hidden) refresh();
  }, REFRESH_MS);

  const userById = (id) => o.users.find((u) => u.id === Number(id));

  // ---- AI DJ ----
  const djSettings = await api.djSettings().catch(() => null);
  let djNow = null;
  const drawDj = (s) => {
    if (!s) return;
    djNow = s;
    if (!s.enabled) {
      djBox.innerHTML = `
        <h2 class="settings-section">AI DJ</h2>
        <div class="setting">
          <div><h3>Off (experimental)</h3><p>A radio host that talks between songs, written by a language model and spoken by a voice model. It’s on the shelf for now: turning it on adds a DJ card to everyone’s Home. Downloaded voices and models are kept either way.</p></div>
          <div class="setting-control"><button class="btn" type="button" data-dj-enable="1">Turn on the DJ</button></div>
        </div>`;
      return;
    }
    const opt = (map, cur) => Object.entries(map).map(([k, v]) => `<option value="${k}"${k === cur ? " selected" : ""}>${esc(v)}</option>`).join("");
    const needsKey = s.provider === "gemini" || s.provider === "anthropic";
    djBox.innerHTML = `
      <h2 class="settings-section">AI DJ</h2>
      <form class="dj-form" data-dj-form>
        <p class="cd-note">The DJ on Home talks between songs. A language model writes what it says and Kokoro, an open voice model on this server, says it. Sent to the model: each person’s first name and the songs’ titles, artists, albums and play counts.</p>
        ${s.voiceReady ? "" : `<p class="dialog-error">The DJ’s voice (Kokoro) isn’t installed on this server, so the DJ can’t talk yet. See “AI DJ” in the README.</p>`}
        <div class="dj-grid">
          <label class="field"><span>Writer</span><select class="select" name="provider">${opt(s.providers, s.provider)}</select></label>
          ${needsKey ? `<label class="field"><span>${s.provider === "gemini" ? "Gemini" : "Claude"} API key</span>
            <input name="key" type="password" autocomplete="off" placeholder="${s.hasKey ? "Saved (type to replace)" : "Paste your key"}"></label>` : ""}
          ${s.provider === "ollama" ? `<label class="field"><span>Ollama address</span><input name="key" placeholder="http://localhost:11434"></label>` : ""}
          ${!["none", "builtin"].includes(s.provider) ? `<label class="field"><span>Model</span><input name="model" value="${esc(s.model)}" placeholder="${esc(s.defaultModel)}"></label>` : ""}
          <label class="field"><span>Voice</span><select class="select" name="voice">
            ${s.natural.installed ? `<optgroup label="Natural (Chatterbox, on the graphics card)">${opt(s.naturalVoices, s.voice)}</optgroup>` : ""}
            <optgroup label="Light (Kokoro, on this server)">${opt(s.voices, s.voice)}</optgroup>
            <optgroup label="Gemini (cloud, uses the Gemini key)">${opt(s.geminiVoices, s.voice)}</optgroup></select></label>
          ${s.voice.startsWith("natural:") ? `<label class="field"><span>Expressiveness</span><select class="select" name="expressive">${opt({ "0.4": "Calm", "0.6": "Lively", "0.85": "Animated" }, String(s.expressive))}</select></label>` : ""}
          <label class="field"><span>Co-host</span><select class="select" name="cohost">
            <option value="">None</option>
            ${s.natural.installed ? `<optgroup label="Natural">${opt(s.naturalVoices, s.cohost)}</optgroup>` : ""}
            <optgroup label="Light">${opt(s.voices, s.cohost)}</optgroup></select></label>
          <label class="field"><span>Speaking speed</span><select class="select" name="speed">${opt({ "0.9": "Relaxed", "1": "Normal", "1.1": "Lively" }, String(s.speed))}</select></label>
        </div>
        ${s.provider === "builtin" ? builtinPart(s) : ""}
        ${s.provider === "gemini" ? `<p class="cd-note">Get a key at aistudio.google.com/apikey (Google’s free tier covers a DJ easily).</p>` : ""}
        ${naturalPart(s)}
        ${s.voice.startsWith("gemini:") && !s.hasGeminiKey ? `<p class="cd-note">Gemini voices need a Gemini key (choose Gemini as the writer to add one). Until then Kokoro speaks.</p>` : ""}
        <label class="field"><span>Pronunciation</span>
          <textarea name="say" rows="3" placeholder="Name = how to say it, one per line, e.g. Slipknot = Slip-not">${esc(s.say)}</textarea>
          <small class="field-hint">For names the voice gets wrong. Built in already: ${esc(["Yungblud", "Måneskin", "Ranieri"].join(", "))}.</small></label>
        ${needsKey && !s.hasKey ? `<p class="cd-note">Without a key the DJ uses built-in lines.</p>` : ""}
        <div class="cd-actions">
          <button class="btn btn-primary" type="submit">Save</button>
          <button class="btn" type="button" data-dj-sample ${s.voiceReady ? "" : "disabled"}><svg><use href="#i-play"/></svg>Hear a sample</button>
          <button class="btn" type="button" data-dj-enable="0">Turn off the DJ</button>
        </div>
        <p class="cd-note dj-sample-text"></p>
      </form>`;
  };
  /** The natural voice: set it up (or see how setting it up is going). */
  function naturalPart(s) {
    const n = s.natural;
    if (n.installing) return `<p class="cd-note"><b>Setting up natural voices:</b> ${esc(n.step)}…</p>`;
    if (n.error) return `<p class="dialog-error">${esc(n.error)}</p>`;
    if (n.installed) return n.device === "cpu" ? `<p class="cd-note">Natural voices are set up, but there’s no graphics card here they can use, so Kokoro speaks.</p>` : "";
    return `<div class="llm-model"><span><b>Natural voices</b> (Chatterbox)<br><small>Close to a real person, male voices included. Needs a graphics card with 4 GB or more (yours is used if there is one); about 3 GB to download. Without one, the light voices keep working.</small></span>
      <button class="btn btn-small" type="button" data-natural-install>Set up</button></div>`;
  }

  /** The built-in writer: pick a model, download it, see how it's going. */
  function builtinPart(s) {
    const b = s.builtin;
    const pct = b.total ? Math.round((b.done / b.total) * 100) : 0;
    return `<div class="llm-models">
      <p class="cd-note">Shelf runs a small language model itself, on the processor: no account or key, and nothing leaves this server. It starts when the DJ needs a line and stops when it’s been idle a while.</p>
      ${Object.entries(b.models).map(([k, m]) => `
        <label class="llm-model">
          <input type="radio" name="model" value="${k}" ${(s.model || "standard") === k ? "checked" : ""}>
          <span><b>${esc(m.name)}</b>${k === "standard" ? " (recommended)" : ""}<br><small>${esc(m.note)}</small></span>
          ${b.installing === k ? `<span class="llm-progress"><span style="width:${pct}%"></span></span><small>${pct}%</small>`
            : m.installed ? `<span class="tag">Downloaded</span><button class="text-btn" type="button" data-llm-remove="${k}">Remove</button>`
            : `<button class="btn btn-small" type="button" data-llm-install="${k}" ${b.installing ? "disabled" : ""}>Download</button>`}
        </label>`).join("")}
      ${b.error ? `<p class="dialog-error">${esc(b.error)}</p>` : ""}
    </div>`;
  }
  let llmPoll = 0;
  const followInstall = async () => {
    clearTimeout(llmPoll);
    const s = await api.djSettings().catch(() => null);
    if (!s) return;
    drawDj(s);
    if (s.builtin?.installing || s.natural?.installing) llmPoll = setTimeout(followInstall, 2000);
  };
  djBox.addEventListener("click", async (e) => {
    const toggle = e.target.closest("[data-dj-enable]");
    if (toggle) {
      e.preventDefault();
      try {
        await api.editDjSettings({ enabled: toggle.dataset.djEnable === "1" });
        location.reload(); // the DJ card and buttons come and go with it
      } catch (err) { toast(err.message); }
      return;
    }
    if (e.target.closest("[data-natural-install]")) {
      e.preventDefault();
      try { drawDj(await api.djNatural()); followInstall(); } catch (err) { toast(err.message); }
      return;
    }
    const inst = e.target.closest("[data-llm-install]");
    const rem = e.target.closest("[data-llm-remove]");
    if (!inst && !rem) return;
    e.preventDefault();
    try {
      if (inst) { drawDj(await api.djInstall(inst.dataset.llmInstall)); followInstall(); }
      else drawDj(await api.djRemove(rem.dataset.llmRemove));
    } catch (err) { toast(err.message); }
  });

  drawDj(djSettings);
  if (djSettings?.builtin?.installing || djSettings?.natural?.installing) followInstall();
  el.querySelector("#dj-slot")?.replaceWith(djBox);
  const djForm = () => djBox.querySelector("form");
  const djValues = () => {
    const f = new FormData(djForm());
    const body = { provider: f.get("provider"), voice: f.get("voice"), speed: Number(f.get("speed")), say: f.get("say") ?? undefined };
    if (f.get("expressive")) body.expressive = Number(f.get("expressive"));
    if (f.get("cohost") != null) body.cohost = f.get("cohost");
    if (f.get("model") != null) body.model = f.get("model");
    if (f.get("key")) body.key = f.get("key");
    return body;
  };
  djBox.addEventListener("change", async (e) => {
    if (e.target.name === "provider") drawDj(await api.editDjSettings({ provider: e.target.value }));
    if (e.target.name === "voice" && djNow) drawDj({ ...djNow, voice: e.target.value });
  });
  djBox.addEventListener("submit", async (e) => {
    e.preventDefault();
    try { drawDj(await api.editDjSettings(djValues())); toast("DJ settings saved"); } catch (err) { toast(err.message); }
  });
  djBox.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-dj-sample]");
    if (!b) return;
    b.disabled = true;
    b.lastChild.textContent = "Thinking…";
    try {
      await api.editDjSettings(djValues());
      const r = await api.djSample();
      djBox.querySelector(".dj-sample-text").textContent = `“${r.text}”`;
      new Audio(r.voice.url).play().catch(() => {});
    } catch (err) { toast(err.message); }
    b.disabled = false;
    b.lastChild.textContent = "Hear a sample";
  });

  // ---- CD drive ----
  let cd = await api.cd().catch(() => null);
  let cdShown = "";
  let cdTimer = 0;
  const drawCd = () => {
    if (!cd?.available) { cdBox.innerHTML = ""; return; }
    const p = cd.progress;
    const key = `${cd.status}|${p?.track}|${cd.error}`;
    if (key === cdShown) return;
    cdShown = key;
    const d = cd.disc;
    const head = `<h2 class="settings-section">CD drive</h2>`;
    if (cd.status === "ready" && d) {
      cdBox.innerHTML = `${head}
        <form class="cd-form" data-cd-form>
          <div class="cd-top">
            ${d.cover ? `<img class="cd-cover" src="api/cd/cover?t=${Date.now()}" alt="">` : `<span class="cd-cover none"><svg><use href="#i-disc"/></svg></span>`}
            <div class="cd-fields">
              ${d.found ? `<p class="cd-note">Found on MusicBrainz. Check the details, then rip.</p>` : `<p class="cd-note">MusicBrainz doesn’t know this disc. Fill in the details.</p>`}
              <label class="field"><span>Artist</span><input name="artist" value="${esc(d.artist)}" required></label>
              <label class="field"><span>Album</span><input name="album" value="${esc(d.album)}" required></label>
              <div class="cd-row"><label class="field"><span>Year</span><input name="year" value="${esc(d.year ?? "")}" inputmode="numeric" maxlength="4"></label>
                ${d.discs > 1 ? `<label class="field"><span>Disc</span><input name="disc" value="${d.disc ?? ""}" inputmode="numeric"></label>` : ""}</div>
            </div>
          </div>
          <ol class="cd-tracks">${d.tracks.map((t, i) => `
            <li><input name="t${i}" value="${esc(t.title)}" aria-label="Track ${i + 1} title"><span>${Math.floor(t.seconds / 60)}:${String(t.seconds % 60).padStart(2, "0")}</span></li>`).join("")}</ol>
          ${cd.error ? `<p class="dialog-error">${esc(cd.error)}</p>` : ""}
          <div class="cd-actions">
            <button class="btn btn-primary" type="submit"><svg><use href="#i-disc"/></svg>Rip to library</button>
            <button class="btn" type="button" data-cd="eject">Eject</button>
          </div>
          <p class="cd-note">Saved as FLAC (lossless) in ${esc(dirs?.folders?.[0]?.path ?? "your music folder")}, as ${esc(d.artist || "Artist")} / ${esc(d.album || "Album")}.</p>
        </form>`;
      return;
    }
    const line = {
      idle: "Put an audio CD in the server’s drive, then read it. Shelf looks it up on MusicBrainz and rips it to FLAC.",
      reading: "Reading the disc and looking it up on MusicBrainz…",
      ripping: p ? `Ripping track ${p.track} of ${p.total}${p.title ? `: ${esc(p.title)}` : ""}. Scratched discs take longer.` : "Ripping…",
      done: cd.result ? `Added ${esc(cd.result.artist)} – ${esc(cd.result.album)}. The disc is ejected, and Shelf is adding it to the library.` : "Done.",
      error: esc(cd.error || "Something went wrong."),
    }[cd.status] ?? "";
    const pct = p ? Math.round((p.done / p.total) * 100) : 0;
    cdBox.innerHTML = `${head}
      <div class="setting cd-status ${cd.status}">
        <div><h3>${{ idle: "Ready", reading: "Reading the disc", ripping: "Ripping", done: "Done", error: "Couldn’t do that" }[cd.status] ?? ""}</h3><p>${line}</p>
          ${cd.status === "ripping" ? `<div class="cd-bar"><span style="width:${pct}%"></span></div>` : ""}</div>
        <div class="setting-control">
          ${cd.status === "ripping" ? `<button class="btn" type="button" data-cd="cancel">Stop</button>`
            : cd.status === "reading" ? "" : `<button class="btn btn-primary" type="button" data-cd="read"><svg><use href="#i-disc"/></svg>${cd.status === "done" ? "Read another disc" : "Read disc"}</button>
              <button class="btn" type="button" data-cd="eject">Eject</button>`}
        </div>
      </div>`;
  };
  const pollCd = async () => {
    cd = await api.cd().catch(() => cd);
    drawCd();
    clearTimeout(cdTimer);
    if (cd && ["reading", "ripping"].includes(cd.status)) cdTimer = setTimeout(pollCd, 1500);
    else if (cd?.status === "done") refresh();
  };
  drawCd();
  if (cd && ["reading", "ripping"].includes(cd.status)) pollCd();
  el.querySelector("#cd-slot")?.replaceWith(cdBox);
  cdBox.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-cd]");
    if (!b) return;
    try {
      if (b.dataset.cd === "read") await api.cdRead();
      if (b.dataset.cd === "eject") await api.cdEject();
      if (b.dataset.cd === "cancel") await api.cdCancel();
    } catch (err) { toast(err.message); }
    cdShown = "";
    pollCd();
  });
  cdBox.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const titles = cd.disc.tracks.map((_, i) => f.get(`t${i}`) || "");
    try {
      await api.cdRip({ artist: f.get("artist"), album: f.get("album"), year: f.get("year") || null,
        disc: f.get("disc") ? Number(f.get("disc")) : null, titles });
    } catch (err) { toast(err.message); return; }
    cdShown = "";
    pollCd();
  });

  async function addPerson() {
    const made = await dialog({
      title: "Add a person",
      text: "They sign in with this username and password, and can change the password in Settings.",
      fields: [
        { name: "username", label: "Username", autocomplete: "off" },
        { name: "password", label: "Password", hint: "At least 6 characters. Share it with them." },
        { name: "admin", label: "Admin", type: "checkbox", hint: "Can add people, change music folders and rescan." },
      ],
      confirm: "Add person",
      submit: (v) => api.createUser({ username: v.username, password: v.password, admin: v.admin }),
    });
    if (!made) return;
    toast(`Added ${made.username}. They can sign in now.`);
    await refresh();
  }

  function personMenu(btn) {
    const u = userById(btn.dataset.id);
    if (!u) return;
    const self = u.id === me.id;
    const fail = (e) => toast(e.message);
    openMenu({
      at: btn,
      header: { title: u.username, sub: u.admin ? "Admin" : "Listener", art: disc(u) },
      items: [
        { label: "Set a new password", icon: "i-key", run: () => resetPassword(u).catch(fail) },
        { label: "Rename", icon: "i-edit", run: () => rename(u).catch(fail) },
        self ? null : { label: u.admin ? "Remove admin" : "Make admin", icon: "i-admin", run: () => setAdmin(u, !u.admin).catch(fail) },
        { label: "Sign out everywhere", icon: "i-close", sub: self ? "Including this device" : null, run: () => signOut(u).catch(fail) },
        ...(self ? [] : ["sep", { label: "Remove account", icon: "i-trash", run: () => remove(u).catch(fail) }]),
      ].filter(Boolean),
    });
  }

  async function resetPassword(u) {
    const ok = await dialog({
      title: `New password for ${u.username}`,
      text: u.id === me.id ? "Your other devices will need the new password." : "They’ll be signed out everywhere and need this password to get back in.",
      fields: [{ name: "password", label: "New password", hint: "At least 6 characters." }],
      confirm: "Set password",
      submit: (v) => api.editUser(u.id, { password: v.password }),
    });
    if (!ok) return;
    toast(`Password changed for ${u.username}`);
    if (u.id === me.id) location.reload(); // this device was signed out too
  }

  async function rename(u) {
    const v = await dialog({
      title: "Rename",
      fields: [{ name: "username", label: "Username", value: u.username }],
      confirm: "Save",
      submit: (x) => api.editUser(u.id, { username: x.username }),
    });
    if (!v) return;
    if (u.id === me.id) session.user = { ...me, username: v.username };
    await refresh();
  }

  async function setAdmin(u, admin) {
    await api.editUser(u.id, { admin });
    toast(admin ? `${u.username} is now an admin` : `${u.username} is no longer an admin`);
    await refresh();
  }

  async function signOut(u) {
    const ok = await dialog({
      title: `Sign ${u.id === me.id ? "yourself" : u.username} out everywhere?`,
      text: "Every phone, computer and browser signed in to this account will need the password again.",
      confirm: "Sign out everywhere",
    });
    if (!ok) return;
    await api.signOutUser(u.id);
    if (u.id === me.id) location.reload();
    else { toast(`Signed ${u.username} out everywhere`); await refresh(); }
  }

  async function remove(u) {
    const ok = await dialog({
      title: `Remove ${u.username}?`,
      text: `Their ${plural(u.likes, "liked song")}, ${plural(u.playlists, "playlist")} and listening history are deleted, and they’re signed out everywhere. The music stays.`,
      confirm: "Remove account", danger: true,
    });
    if (!ok) return;
    await api.deleteUser(u.id);
    toast(`Removed ${u.username}`);
    await refresh();
  }

  /** Add music: drop songs, folders or ZIPs; they're filed by their tags, then the library rescans. */
  function uploadDialog() {
    const roots = (dirs?.folders ?? []).filter((f) => f.available).map((f) => f.path);
    const d = document.createElement("dialog");
    d.className = "dialog upload-dialog";
    d.innerHTML = `
      <form method="dialog">
        <h2>Add music</h2>
        <p>Songs are filed into Artist / Album folders from their tags. ZIP files are unpacked, and cover pictures go with their album.</p>
        ${roots.length > 1 ? `<label class="field"><span>Into</span><select name="folder" class="select">${roots.map((r) => `<option>${esc(r)}</option>`).join("")}</select></label>` : ""}
        <label class="drop-zone" tabindex="0">
          <input type="file" multiple accept="audio/*,.flac,.mp3,.m4a,.ogg,.opus,.wav,.aiff,.ape,.wv,.zip,image/*" hidden>
          <svg aria-hidden="true"><use href="#i-upload"/></svg>
          <b>Drop songs, album folders or ZIP files here</b>
          <span>or <u>choose files</u>, or <button type="button" class="text-btn pick-folder">choose a folder</button></span>
        </label>
        <ul class="upload-list"></ul>
        <p class="dialog-error" role="alert"></p>
        <div class="dialog-actions"><button class="btn" type="button" value="close">Close</button></div>
      </form>`;
    document.body.append(d);
    const input = d.querySelector("input[type=file]");
    const zone = d.querySelector(".drop-zone");
    const list = d.querySelector(".upload-list");
    let busy = false, added = 0;
    d.querySelector('[value="close"]').addEventListener("click", () => { if (!busy) d.close(); });
    d.addEventListener("cancel", (e) => { if (busy) e.preventDefault(); });
    d.addEventListener("close", () => {
      d.remove();
      if (added) api.rescan().then(() => { toast(`Added ${plural(added, "file")}. Shelf is adding them to the library now.`, 5000); refresh(); }).catch(() => {});
    });
    d.querySelector(".pick-folder").addEventListener("click", (e) => {
      e.preventDefault();
      const f = document.createElement("input");
      f.type = "file"; f.multiple = true; f.webkitdirectory = true;
      f.addEventListener("change", () => send([...f.files].map((file) => ({ file, path: file.webkitRelativePath }))));
      f.click();
    });
    input.addEventListener("change", () => send([...input.files].map((file) => ({ file, path: file.name }))));
    zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("over"); });
    zone.addEventListener("dragleave", () => zone.classList.remove("over"));
    zone.addEventListener("drop", async (e) => {
      e.preventDefault();
      zone.classList.remove("over");
      send(await droppedFiles(e.dataTransfer));
    });

    async function send(items) {
      const ok = items.filter(({ file }) => /\.(flac|mp3|m4a|mp4|aac|alac|ogg|oga|opus|wav|aif|aiff|wma|ape|wv|zip|jpe?g|png|webp)$/i.test(file.name));
      if (!ok.length) { d.querySelector(".dialog-error").textContent = "None of those are songs, pictures or ZIP files."; return; }
      // Songs first, so each album's cover finds the folder its songs went to.
      ok.sort((a, b) => /\.(jpe?g|png|webp)$/i.test(a.file.name) - /\.(jpe?g|png|webp)$/i.test(b.file.name));
      busy = true;
      d.querySelector(".dialog-error").textContent = "";
      const folder = d.querySelector("select[name=folder]")?.value ?? "";
      const batch = Date.now().toString(36);
      for (const { file, path } of ok) {
        const li = document.createElement("li");
        li.innerHTML = `<span class="up-name">${esc(path)}</span><span class="up-state">Waiting</span>`;
        list.append(li);
      }
      const rows = [...list.children].slice(-ok.length);
      for (let i = 0; i < ok.length; i++) {
        const { file, path } = ok[i];
        const state = rows[i].querySelector(".up-state");
        state.textContent = "Sending…";
        rows[i].scrollIntoView({ block: "nearest" });
        const group = `${batch}/${path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : ""}`;
        try {
          const r = await uploadFile(file, { name: file.name, folder, group }, (p) => { state.textContent = `${Math.round(p * 100)}%`; });
          if (r.status === "added") added += r.added ?? 1;
          state.textContent = r.status === "added" ? (r.albums?.length ? `Added: ${r.albums.join(", ")}` : r.album ? `Added to ${r.artist} – ${r.album}` : "Added")
            : r.status === "duplicate" ? "Already there" : (r.reason || "Skipped");
          rows[i].classList.add(r.status);
        } catch (err) {
          state.textContent = err.message;
          rows[i].classList.add("failed");
        }
      }
      busy = false;
    }
    d.showModal();
  }

  /** Update this server, then wait for it to come back as the new version and reload. */
  async function updateNow(b) {
    b.disabled = true;
    b.textContent = "Updating…";
    try {
      const r = await api.updateServer();
      toast(r.message);
      const want = r.latest;
      const started = Date.now();
      const poll = async () => {
        try {
          const ping = await fetch("api/ping", { cache: "no-store" }).then((x) => x.json());
          if (ping.version === want) { toast(`Shelf is now ${want}`); setTimeout(() => location.reload(), 800); return; }
        } catch { /* restarting */ }
        if (Date.now() - started < 10 * 60_000) setTimeout(poll, 3000);
        else toast("The update is taking a while. Check the server, then reload this page.");
      };
      setTimeout(poll, 4000);
    } catch (err) {
      toast(err.message);
      b.disabled = false;
      b.textContent = "Update now";
    }
  }

  const onClick = (e) => {
    const b = e.target.closest("[data-admin]");
    if (!b || !el.contains(b)) return;
    if (b.dataset.admin === "upload") uploadDialog();
    if (b.dataset.admin === "unlock" || b.dataset.admin === "unlock-all") {
      const address = b.dataset.admin === "unlock" ? b.dataset.address : null;
      api.clearSignins(address)
        .then(() => { toast(address ? `${address} can sign in again` : "All sign-in lockouts cleared"); return refresh(); })
        .catch((err) => toast(err.message));
    }
    if (b.dataset.admin === "person-add") addPerson().catch((err) => toast(err.message));
    if (b.dataset.admin === "update-check") {
      api.checkUpdate().then((u) => {
        toast(u.error ?? (u.available ? `Shelf ${u.latest} is out` : `Shelf ${u.current} is the latest version`));
        return refresh();
      }).catch((err) => toast(err.message));
    }
    if (b.dataset.admin === "update-now") updateNow(b);
    if (b.dataset.admin === "lastfm") {
      dialog({
        title: "Last.fm API account",
        text: "Make one at last.fm/api/account/create (any name; the callback URL can stay empty), then paste its API key and shared secret here.",
        fields: [{ name: "key", label: "API key" }, { name: "secret", label: "Shared secret" }],
        confirm: "Save",
        submit: (v) => api.setLastfmKeys(v.key.trim(), v.secret.trim()),
      }).then((r) => { if (r) { toast(r.configured ? "Last.fm is set up: people can connect it in Settings" : "Last.fm removed"); refresh(); } })
        .catch((err) => toast(err.message));
    }
    if (b.dataset.admin === "update-auto") {
      const on = b.getAttribute("aria-checked") !== "true";
      api.autoUpdate(on).then((u) => {
        b.setAttribute("aria-checked", String(!!u.auto));
        toast(u.auto ? "Shelf installs updates by itself now, at night" : "Shelf only updates when you choose Update now");
      }).catch((err) => toast(err.message));
    }
    if (b.dataset.admin === "health-check") checkHealth();
    if (b.dataset.admin === "covers-find") {
      b.disabled = true;
      api.findMissingCovers().then(() => { toast("Looking for covers: one album a second"); checkHealth(); })
        .catch((err) => { toast(err.message); b.disabled = false; });
    }
    if (b.dataset.admin === "cover-choose") chooseCover(Number(b.dataset.id), b.dataset.title, checkHealth);
    if (b.dataset.admin === "backup-now") {
      b.disabled = true;
      api.backUpNow().then(() => { toast("Backed up"); refresh(); })
        .catch((err) => { toast(err.message); b.disabled = false; });
    }
    if (b.dataset.admin === "backup-restore") {
      dialog({
        title: "Restore this backup?",
        text: `Accounts, Favourites, playlists and play history go back to how they were on ${b.dataset.when}. Anything since is replaced, but Shelf backs up what’s here now first, so you can undo this by restoring that copy.`,
        confirm: "Restore", danger: true,
        submit: () => api.restoreBackup(b.dataset.name),
      }).then((r) => { if (r) { toast("Restored. Reloading…"); setTimeout(() => location.reload(), 1200); } })
        .catch((err) => toast(err.message));
    }
    if (b.dataset.admin === "person-menu") personMenu(b);
  };
  let healthPoll = 0;
  async function checkHealth() {
    const btn = healthBox.querySelector('[data-admin="health-check"]');
    if (btn) { btn.disabled = true; btn.textContent = "Checking…"; }
    try {
      const r = await api.libraryHealth();
      const open = [...healthBox.querySelectorAll("details[open]")].map((d) => d.dataset.kind);
      healthBox.innerHTML = healthHtml(r);
      for (const k of open) healthBox.querySelector(`details[data-kind="${k}"]`)?.setAttribute("open", "");
      clearTimeout(healthPoll);
      if (r.finder.running) healthPoll = setTimeout(checkHealth, 3000); // the cover search is still going
      else if (r.finder.finishedAt && Date.now() / 1000 - r.finder.finishedAt < 8 && r.finder.done) refresh();
    } catch (err) {
      toast(err.message);
      if (btn) { btn.disabled = false; btn.textContent = "Check library"; }
    }
  }

  el.addEventListener("click", onClick);
  return () => { clearTimeout(healthPoll); clearInterval(timer); clearTimeout(cdTimer); clearTimeout(llmPoll); el.removeEventListener("click", onClick); };
}


/** Files dropped on the page, folders included (walked), each with its path inside the drop. */
async function droppedFiles(dt) {
  const out = [];
  const walk = async (entry, prefix) => {
    if (entry.isFile) {
      const file = await new Promise((res, rej) => entry.file(res, rej));
      out.push({ file, path: prefix + file.name });
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      for (;;) {
        const batch = await new Promise((res, rej) => reader.readEntries(res, rej));
        if (!batch.length) break;
        for (const e of batch) await walk(e, `${prefix}${entry.name}/`);
      }
    }
  };
  const entries = [...dt.items].map((it) => it.webkitGetAsEntry?.()).filter(Boolean);
  if (entries.length) for (const e of entries) await walk(e, "");
  else for (const file of dt.files) out.push({ file, path: file.name });
  return out;
}

/** Send one file as the request body, reporting progress (0..1). */
function uploadFile(file, { name, folder, group }, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const q = new URLSearchParams({ name, group, ...(folder ? { folder } : {}) });
    xhr.open("POST", `api/upload?${q}`);
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded / e.total); };
    xhr.onload = () => {
      let body = null;
      try { body = JSON.parse(xhr.responseText); } catch { /* not JSON */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body);
      else reject(new Error(body?.detail || `Failed (${xhr.status})`));
    };
    xhr.onerror = () => reject(new Error("Lost the connection"));
    xhr.send(file);
  });
}
