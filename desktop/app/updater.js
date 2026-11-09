// Keeping the desktop player up to date, in the background.
//
// Every six hours (and shortly after starting) it looks at Shelf's latest GitHub release.
// - Windows installer and .deb: electron-updater downloads the new version quietly and installs
//   it when Shelf is closed (the .deb asks for your password then, as installing a package does).
// - Flatpak: the app can't replace itself from inside its sandbox, so it downloads the new
//   bundle and asks Flatpak on the computer to install it (flatpak-spawn --host). The new
//   version starts the next time Shelf is opened.
// Either way a notification says when an update is ready.

const { app, net, Notification } = require("electron");
const { execFile } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const REPO = "Spinjitsudoom/shelf";
const CHECK_MS = 6 * 60 * 60 * 1000;
const FLATPAK = !!process.env.FLATPAK_ID || fs.existsSync("/.flatpak-info");

const parse = (v) => String(v).replace(/^v/i, "").split(".").map((n) => parseInt(n, 10) || 0);
function newer(a, b) {
  const x = parse(a), y = parse(b);
  for (let i = 0; i < Math.max(x.length, y.length); i++) if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) > (y[i] || 0);
  return false;
}

function notify(title, body) {
  if (Notification.isSupported()) new Notification({ title, body, silent: true }).show();
}

function start() {
  if (!app.isPackaged || process.env.SHELF_NO_UPDATES) return;
  const check = FLATPAK ? flatpakCheck : nativeCheck();
  setTimeout(check, 15_000);
  setInterval(check, CHECK_MS);
}

/** Windows (NSIS) and .deb: electron-updater, from the release's latest*.yml. */
function nativeCheck() {
  const { autoUpdater } = require("electron-updater");
  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = true;
  autoUpdater.logger = null;
  let told = "";
  autoUpdater.on("update-downloaded", (info) => {
    if (told === info.version) return;
    told = info.version;
    notify(`Shelf ${info.version} is ready`, "It installs when you close Shelf.");
  });
  autoUpdater.on("error", (e) => console.warn("Update check failed:", e?.message || e));
  return () => autoUpdater.checkForUpdates().catch(() => {});
}

/** Flatpak: download the new bundle and have the computer's Flatpak install it. */
let flatpakBusy = false;
let flatpakDone = "";
async function flatpakCheck() {
  if (flatpakBusy) return;
  flatpakBusy = true;
  try {
    const res = await net.fetch(`https://api.github.com/repos/${REPO}/releases/latest`, {
      headers: { Accept: "application/vnd.github+json" },
    });
    if (!res.ok) return;
    const rel = await res.json();
    const latest = String(rel.tag_name || "").replace(/^v/i, "");
    if (!latest || latest === flatpakDone || !newer(latest, app.getVersion())) return;
    const asset = (rel.assets || []).find((a) => a.name.endsWith(".flatpak"));
    if (!asset) return;
    const dir = process.env.XDG_CACHE_HOME || path.join(app.getPath("home"), ".cache");
    fs.mkdirSync(dir, { recursive: true });
    const file = path.join(dir, asset.name);
    const data = await net.fetch(asset.browser_download_url);
    if (!data.ok) return;
    fs.writeFileSync(file, Buffer.from(await data.arrayBuffer()));
    // Installed for this user or for everyone? Update it the same way.
    const info = fs.readFileSync("/.flatpak-info", "utf8");
    const scope = /app-path=.*\/\.local\/share\/flatpak\//.test(info) ? "--user" : "--system";
    await new Promise((resolve, reject) => execFile("flatpak-spawn",
      ["--host", "flatpak", "install", scope, "--reinstall", "--noninteractive", "-y", file],
      { timeout: 10 * 60_000 }, (err, _out, stderr) => (err ? reject(new Error(stderr || err.message)) : resolve())));
    fs.rmSync(file, { force: true });
    flatpakDone = latest;
    notify(`Shelf ${latest} is installed`, "It starts the next time you open Shelf.");
  } catch (e) {
    console.warn("Flatpak update failed:", e?.message || e);
  } finally {
    flatpakBusy = false;
  }
}

module.exports = { start, newer };
