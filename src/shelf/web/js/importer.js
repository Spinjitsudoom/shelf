// Importing playlists from elsewhere (see src/shelf/imports.py): a Spotify or YouTube link, a
// playlist file from another player, a CSV export, Spotify's data download, or a pasted list.
// The server finds each song in the library; this shows what it found before anything is made.

import { api } from "./api.js";
import { caseHtml, esc, plural } from "./util.js";

const FILES = ".m3u,.m3u8,.pls,.xspf,.csv,.tsv,.txt,.json";
const MAX_FILE = 8 * 1024 * 1024;

function songRow(s) {
  if (!s.track) {
    return `<li class="imp-song imp-missing"><span class="imp-dot" aria-hidden="true"></span>
      <span class="t-main"><span class="t-title">${esc(s.want)}</span><span class="t-sub">Not in your library</span></span></li>`;
  }
  const t = s.track;
  return `<li class="imp-song">${caseHtml(t, { size: 160, cls: "case-sm", sizes: "36px" })}
    <span class="t-main"><span class="t-title">${esc(t.title)}</span><span class="t-sub">${esc(t.artist)}</span></span></li>`;
}

function resultHtml(found, many) {
  return found.playlists.map((p, i) => {
    const ids = [...new Set(p.songs.filter((s) => s.track).map((s) => s.track.id))];
    const missing = p.songs.length - p.found;
    return `
      <section class="imp-list" data-i="${i}">
        <div class="imp-head">
          ${many ? `<input type="checkbox" name="pick" value="${i}"${ids.length ? " checked" : " disabled"} aria-label="Import ${esc(p.name)}">` : ""}
          <label class="field imp-name"><span>${many ? "Playlist" : "Name"}</span>
            <input name="name-${i}" value="${esc(p.name)}" maxlength="200"></label>
        </div>
        <p class="imp-count"><b>${p.found} of ${plural(p.songs.length, "song")}</b> ${p.found === 1 ? "is" : "are"} in your library.${missing ? ` ${missing} ${missing === 1 ? "isn’t" : "aren’t"}.` : ""}</p>
        <details${many ? "" : " open"}><summary>Show the songs</summary>
          <ol class="imp-songs">${p.songs.map(songRow).join("")}</ol>
          ${missing ? `<button class="text-btn" type="button" data-imp="copy" data-i="${i}">Copy the missing songs</button>` : ""}
        </details>
      </section>`;
  }).join("");
}

/** Opens the import dialog. Resolves to the playlists made ([{id, name}]), or null. */
export function importPlaylists() {
  const d = document.createElement("dialog");
  d.className = "dialog imp-dialog";
  d.innerHTML = `
    <form method="dialog">
      <h2>Import a playlist</h2>
      <div class="imp-step"></div>
      <p class="dialog-error" role="alert"></p>
      <div class="dialog-actions"></div>
    </form>`;
  document.body.append(d);
  const form = d.querySelector("form");
  const step = d.querySelector(".imp-step");
  const actions = d.querySelector(".dialog-actions");
  const err = d.querySelector(".dialog-error");
  let file = null;       // {name, text}
  let found = null;      // the server's answer
  let pasted = "";

  const ask = () => {
    found = null;
    step.innerHTML = `
      <p>From Spotify or YouTube, another music player, or a list of songs. Shelf finds them in your library and makes a playlist of what it has.</p>
      <label class="field"><span>Link or list of songs</span>
        <textarea name="text" rows="5" spellcheck="false" placeholder="https://open.spotify.com/playlist/…&#10;or one song per line, like “Queen - Bohemian Rhapsody”">${esc(pasted)}</textarea></label>
      <div class="imp-file">
        <button class="btn btn-small" type="button" data-imp="file"><svg><use href="#i-upload"/></svg>Choose a file</button>
        <span class="imp-file-name">${file ? esc(file.name) : ""}</span>
        <input type="file" accept="${FILES}" hidden>
      </div>
      <p class="field-hint">Spotify and YouTube links show up to 100 songs. Files: M3U, PLS and XSPF playlists, CSV exports (Exportify, TuneMyMusic and the like), and Spotify’s own data download (Playlist1.json).</p>`;
    actions.innerHTML = `<button class="btn" type="button" data-imp="cancel">Cancel</button>
      <button class="btn btn-primary" type="submit">Find the songs</button>`;
    step.querySelector('input[type="file"]').addEventListener("change", async (e) => {
      const f = e.target.files[0];
      if (!f) return;
      if (f.size > MAX_FILE) { err.textContent = "That file is too big to be a playlist."; return; }
      file = { name: f.name, text: await f.text() };
      step.querySelector(".imp-file-name").textContent = f.name;
      form.elements.text.value = "";
      err.textContent = "";
    });
    form.elements.text.focus();
  };

  const show = () => {
    const many = found.playlists.length > 1;
    step.innerHTML = (many ? `<p>${plural(found.playlists.length, "playlist")} found. Pick the ones to import.</p>` : "")
      + `<div class="imp-results">${resultHtml(found, many)}</div>`;
    const total = found.playlists.reduce((n, p) => n + p.found, 0);
    actions.innerHTML = `<button class="btn" type="button" data-imp="back">Back</button>
      <button class="btn btn-primary" type="submit"${total ? "" : " disabled"}>${many ? "Import" : "Make the playlist"}</button>`;
    if (!total) err.textContent = "None of these songs are in your library.";
  };

  const make = async () => {
    const many = found.playlists.length > 1;
    const picked = many ? [...form.querySelectorAll('input[name="pick"]:checked')].map((c) => Number(c.value))
      : [0];
    if (!picked.length) throw new Error("Pick at least one playlist.");
    const made = [];
    for (const i of picked) {
      const p = found.playlists[i];
      const trackIds = [...new Set(p.songs.filter((s) => s.track).map((s) => s.track.id))];
      if (!trackIds.length) continue;
      const missing = p.songs.length - p.found;
      const name = form.elements[`name-${i}`].value.trim() || p.name;
      const description = `Imported${found.linked ? " from a link" : ""}.${missing ? ` ${plural(missing, "song")} ${missing === 1 ? "wasn’t" : "weren’t"} in the library.` : ""}`;
      const pl = await api.createPlaylist({ name, description, trackIds });
      made.push({ id: pl.id, name: pl.name, count: trackIds.length });
    }
    return made;
  };

  return new Promise((resolve) => {
    let result = null;
    d.addEventListener("close", () => { d.remove(); resolve(result); });
    d.addEventListener("click", (e) => {
      const b = e.target.closest("[data-imp]");
      if (!b) return;
      const what = b.dataset.imp;
      if (what === "cancel") d.close();
      if (what === "file") step.querySelector('input[type="file"]').click();
      if (what === "back") { err.textContent = ""; ask(); }
      if (what === "copy") {
        const p = found.playlists[Number(b.dataset.i)];
        const text = p.songs.filter((s) => !s.track).map((s) => s.want).join("\n");
        navigator.clipboard?.writeText(text).then(() => { b.textContent = "Copied"; }, () => {});
      }
    });
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const go = form.querySelector('button[type="submit"]');
      err.textContent = "";
      go.disabled = true;
      try {
        if (!found) {
          pasted = form.elements.text.value;
          const text = pasted.trim() ? pasted : file?.text ?? "";
          if (!text.trim()) throw new Error("Paste a link or a list of songs, or choose a file.");
          go.textContent = /^https?:\/\//i.test(text.trim()) ? "Opening the link…" : "Finding the songs…";
          found = await api.importPlaylists(text, pasted.trim() ? "" : file?.name ?? "");
          show();
        } else {
          go.textContent = "Making…";
          result = await make();
          d.close();
        }
      } catch (ex) {
        err.textContent = ex.message;
        if (!found) { go.textContent = "Find the songs"; go.disabled = false; } else { go.disabled = false; go.textContent = found.playlists.length > 1 ? "Import" : "Make the playlist"; }
      }
    });
    ask();
    d.showModal();
  });
}
