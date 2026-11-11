// Smart playlists: the rules editor. Rules pick the songs ("not played in 6 months", "under 100
// BPM", "added this week"); the server works them out each time the playlist is opened.

import { api } from "./api.js";
import { esc, plural } from "./util.js";

const FIELDS = [
  ["genre", "Genre", "text"], ["artist", "Artist", "text"], ["album", "Album", "text"], ["title", "Title", "text"],
  ["year", "Year", "number"], ["bpm", "Tempo (BPM)", "number"], ["duration", "Length in minutes", "number"],
  ["plays", "Times I’ve played it", "number"], ["lastPlayed", "Last played", "days"], ["added", "Date added", "days"],
  ["favourite", "In my Favourites", "flag"], ["lossless", "Lossless quality", "flag"], ["mood", "Mood", "mood"],
];
const KIND = Object.fromEntries(FIELDS.map(([k, , kind]) => [k, kind]));
const OPS = {
  text: [["contains", "contains"], ["is", "is"], ["isNot", "isn’t"], ["notContains", "doesn’t contain"]],
  number: [["atLeast", "at least"], ["atMost", "at most"], ["is", "is"], ["between", "between"]],
  days: [["within", "in the last"], ["notWithin", "not in the last"]],
  flag: [["is", "is"]],
  mood: [["is", "is"], ["isNot", "isn’t"]],
};
const MOODS = [["workout", "Workout"], ["chill", "Chill"], ["party", "Party"], ["feel-good", "Feel Good"],
  ["melancholy", "Melancholy"], ["heavy", "Heavy"]];
const UNITS = [[365, "years"], [30, "months"], [7, "weeks"], [1, "days"]];
const SORTS = [["artist", "Artist"], ["title", "Title"], ["added", "Newest additions first"], ["lastPlayed", "Recently played first"],
  ["mostPlayed", "Most played first"], ["leastPlayed", "Least played first"], ["year", "Oldest first"], ["bpm", "Slowest first"],
  ["random", "Random (new every day)"]];

const options = (list, chosen) => list.map(([v, t]) => `<option value="${esc(String(v))}"${String(v) === String(chosen) ? " selected" : ""}>${esc(t)}</option>`).join("");

function opsFor(field) {
  const ops = OPS[KIND[field]];
  return field === "lastPlayed" ? [...ops, ["never", "never"]] : ops;
}

/** The value part of a rule, which depends on its field and how it's compared. */
function valueHtml(c) {
  const kind = KIND[c.field];
  if (kind === "text") return `<input class="smart-text" name="v" value="${esc(c.value ?? "")}" maxlength="200" placeholder="Type here" aria-label="What to look for">`;
  if (kind === "flag") return `<select class="select" name="v" aria-label="Yes or no">${options([["true", "yes"], ["false", "no"]], String(c.value !== false))}</select>`;
  if (kind === "mood") return `<select class="select" name="v" aria-label="Mood">${options(MOODS, c.value ?? "workout")}</select>`;
  if (kind === "days") {
    if (c.op === "never") return "";
    const days = Number(c.value) || 30;
    const [size] = UNITS.find(([u]) => days % u === 0);
    return `<input class="smart-num" name="v" type="number" min="1" max="999" value="${days / size}" aria-label="How many">
      <select class="select" name="unit" aria-label="Days, weeks, months or years">${options(UNITS, size)}</select>`;
  }
  if (c.op === "between") {
    const [a, b] = Array.isArray(c.value) ? c.value : ["", ""];
    return `<input class="smart-num" name="v" type="number" step="any" value="${esc(String(a))}" aria-label="From">
      <span class="smart-and">and</span><input class="smart-num" name="v2" type="number" step="any" value="${esc(String(b))}" aria-label="To">`;
  }
  return `<input class="smart-num" name="v" type="number" step="any" value="${esc(String(Array.isArray(c.value) ? c.value[0] : c.value ?? ""))}" aria-label="Number">`;
}

function ruleHtml(c, i) {
  return `
    <div class="smart-rule" data-i="${i}">
      <select class="select" name="field" aria-label="What to pick by">${options(FIELDS.map(([k, label]) => [k, label]), c.field)}</select>
      <select class="select" name="op" aria-label="How to compare">${options(opsFor(c.field), c.op)}</select>
      <span class="smart-value">${valueHtml(c)}</span>
      <button class="icon-btn" type="button" data-smart="remove" aria-label="Remove this rule" title="Remove"><svg><use href="#i-close"/></svg></button>
    </div>`;
}

/** A rule's value as typed, as the server wants it; undefined while it's unfinished. */
function readRule(row) {
  const field = row.querySelector('[name="field"]').value;
  const op = row.querySelector('[name="op"]').value;
  const kind = KIND[field];
  const v = row.querySelector('[name="v"]');
  const v2 = row.querySelector('[name="v2"]');
  let value;
  if (!v && !(kind === "days" && op === "never")) return { field, op, value: undefined }; // the comparison just changed
  if (kind === "text") value = v.value.trim() || undefined;
  else if (kind === "flag") value = v.value === "true";
  else if (kind === "mood") value = v.value;
  else if (kind === "days") value = op === "never" ? null : (Number(v.value) > 0 ? Math.round(Number(v.value) * Number(row.querySelector('[name="unit"]').value)) : undefined);
  else if (op === "between") {
    const a = v.value === "" ? NaN : Number(v.value), b = !v2 || v2.value === "" ? NaN : Number(v2.value);
    value = Number.isFinite(a) && Number.isFinite(b) ? [a, b] : undefined;
  } else value = v.value === "" || !Number.isFinite(Number(v.value)) ? undefined : Number(v.value);
  return { field, op, value };
}

/** A fresh rule for a field, keeping the comparison when it still applies. */
function fresh(field, op) {
  const ops = opsFor(field).map(([o]) => o);
  const keep = ops.includes(op) ? op : ops[0];
  const kind = KIND[field];
  const value = kind === "flag" ? true : kind === "mood" ? "workout" : kind === "days" ? 30 : kind === "text" ? "" : undefined;
  return { field, op: keep, value };
}

/**
 * Opens the editor. Resolves to {name, rules} (name only when `askName`), or null if cancelled.
 */
export function editRules({ title = "Smart playlist", rules = null, name = "", askName = false, confirm = "Save" } = {}) {
  let conds = (rules?.conditions ?? [{ field: "added", op: "within", value: 30 }]).map((c) => ({ ...c }));
  const d = document.createElement("dialog");
  d.className = "dialog smart-dialog";
  d.innerHTML = `
    <form method="dialog">
      <h2>${esc(title)}</h2>
      <p>Pick songs by rules. The playlist keeps itself up to date: songs join and leave as they fit.</p>
      ${askName ? `<label class="field"><span>Name</span><input name="name" value="${esc(name)}" maxlength="200" placeholder="My smart playlist"></label>` : ""}
      <div class="smart-match">Songs that match
        <select class="select" name="match" aria-label="All or any of the rules">${options([["all", "all"], ["any", "any"]], rules?.match ?? "all")}</select>
        of these rules:</div>
      <div class="smart-rules"></div>
      <button class="text-btn smart-add" type="button" data-smart="add"><svg><use href="#i-plus"/></svg>Add a rule</button>
      <div class="smart-extra">
        <label class="smart-limit"><input type="checkbox" name="limited"${rules?.limit ? " checked" : ""}> Keep
          <input class="smart-num" name="limit" type="number" min="1" max="5000" value="${rules?.limit ?? 50}" aria-label="How many songs"> songs</label>
        <label class="smart-sort">Order <select class="select" name="sort">${options(SORTS, rules?.sort ?? "artist")}</select></label>
      </div>
      <p class="smart-preview" aria-live="polite"></p>
      <p class="dialog-error" role="alert"></p>
      <div class="dialog-actions">
        <button class="btn" type="button" value="cancel">Cancel</button>
        <button class="btn btn-primary" type="submit" value="ok">${esc(confirm)}</button>
      </div>
    </form>`;
  document.body.append(d);
  const form = d.querySelector("form");
  const list = d.querySelector(".smart-rules");
  const preview = d.querySelector(".smart-preview");
  const drawRules = () => {
    list.innerHTML = conds.map(ruleHtml).join("") || `<p class="smart-none">No rules: every song in the library.</p>`;
  };
  const read = () => {
    conds = [...list.querySelectorAll(".smart-rule")].map(readRule);
    const out = {
      match: form.elements.match.value,
      conditions: conds.filter((c) => c.value !== undefined),
      sort: form.elements.sort.value,
      limit: form.elements.limited.checked ? Math.max(1, Math.min(5000, Number(form.elements.limit.value) || 50)) : null,
    };
    return { rules: out, unfinished: conds.some((c) => c.value === undefined) };
  };
  let timer = 0, asked = 0;
  const refresh = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const { rules: r } = read();
      const mine = ++asked;
      try {
        const p = await api.previewRules(r);
        if (mine === asked) preview.innerHTML = `<b>${plural(p.count, "song")}</b> fit right now. ${esc(p.text)}.`;
      } catch (e) { if (mine === asked) preview.textContent = e.message; }
    }, 250);
  };
  drawRules();
  refresh();

  return new Promise((resolve) => {
    let result = null;
    d.addEventListener("close", () => { d.remove(); resolve(result); });
    d.querySelector('[value="cancel"]').addEventListener("click", () => d.close("cancel"));
    d.addEventListener("click", (e) => {
      const b = e.target.closest("[data-smart]");
      if (!b) return;
      read();
      if (b.dataset.smart === "add") conds.push(fresh("genre", "contains"));
      if (b.dataset.smart === "remove") conds.splice(Number(b.closest(".smart-rule").dataset.i), 1);
      drawRules();
      if (b.dataset.smart === "add") list.querySelector(".smart-rule:last-child input, .smart-rule:last-child select")?.focus();
      refresh();
    });
    d.addEventListener("change", (e) => {
      const row = e.target.closest(".smart-rule");
      if (row && (e.target.name === "field" || e.target.name === "op")) {
        read();
        const i = Number(row.dataset.i);
        const c = conds[i];
        // A new field starts fresh; a new comparison keeps what was typed where it still fits.
        if (e.target.name === "field") conds[i] = fresh(c.field, c.op);
        else if (c.op === "never") c.value = null;
        else if (KIND[c.field] === "days" && !(c.value > 0)) c.value = 30;
        drawRules();
      }
      refresh();
    });
    d.addEventListener("input", (e) => { if (e.target.matches("input")) refresh(); });
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const { rules: r, unfinished } = read();
      const err = d.querySelector(".dialog-error");
      if (unfinished) { err.textContent = "Finish or remove the rules that are still empty."; return; }
      result = { rules: r, name: askName ? form.elements.name.value.trim() : undefined };
      d.close("ok");
    });
    d.showModal();
    (askName ? form.elements.name : list.querySelector("input, select"))?.focus();
  });
}
