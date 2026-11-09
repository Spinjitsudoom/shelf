// Shelf for Windows and Linux: a window onto your Shelf server.
//
// The first time, it asks for the server's address (start.html), checks there's a Shelf
// server there and remembers it. After that it opens straight onto the server's web app.
// Playback controls come from the web app's media session: the keyboard's media keys,
// Windows' media overlay and Linux's desktop player controls (MPRIS) all work with it.

const { app, BrowserWindow, ipcMain, Menu, net, session, shell } = require("electron");
const updater = require("./updater");
const fs = require("node:fs");
const path = require("node:path");

// Connect can start music on this computer from another device, with nobody clicking here.
app.commandLine.appendSwitch("autoplay-policy", "no-user-gesture-required");
app.setName("Shelf");
if (process.platform === "win32") app.setAppUserModelId("io.github.spinjitsudoom.Shelf");

const START = path.join(__dirname, "start.html");
const settingsFile = () => path.join(app.getPath("userData"), "settings.json");
let win = null;

function readSettings() {
  try { return JSON.parse(fs.readFileSync(settingsFile(), "utf8")); } catch { return {}; }
}

function writeSettings(patch) {
  const next = { ...readSettings(), ...patch };
  fs.mkdirSync(path.dirname(settingsFile()), { recursive: true });
  fs.writeFileSync(settingsFile(), JSON.stringify(next, null, 2));
  return next;
}

/** What was typed ("192.168.1.20:4533") as a full address, or null. Same rules as the web app. */
function normalize(input) {
  let s = String(input || "").trim();
  if (!s) return null;
  if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(s)) s = `http://${s}`;
  try {
    const u = new URL(s);
    if (!/^https?:$/.test(u.protocol) || !u.hostname) return null;
    return `${u.origin}${u.pathname.replace(/\/(index\.html)?$/, "")}`;
  } catch {
    return null;
  }
}

/** Null if a Shelf server answers at `url`, else a message to show. */
async function check(url) {
  try {
    const res = await net.fetch(`${url}/api/ping`, { cache: "no-store", signal: AbortSignal.timeout(7000) });
    const body = res.ok ? await res.json().catch(() => null) : null;
    return body?.app === "shelf" ? null : `${url.replace(/^https?:\/\//, "")} answered, but it isn’t a Shelf server.`;
  } catch {
    return `Couldn’t reach ${url.replace(/^https?:\/\//, "")}. Check the address, and that the server is running and on the same network.`;
  }
}

function showStart(error = "") {
  const server = (readSettings().server || "").replace(/^https?:\/\//, "");
  win.loadFile(START, { query: { server, error } });
}

function openServer() {
  const { server } = readSettings();
  if (server) win.loadURL(`${server}/`);
  else showStart();
}

const serverOrigin = () => {
  try { return new URL(readSettings().server).origin; } catch { return null; }
};

function createWindow() {
  const saved = readSettings().bounds;
  win = new BrowserWindow({
    width: saved?.width ?? 1280,
    height: saved?.height ?? 820,
    x: saved?.x,
    y: saved?.y,
    minWidth: 360,
    minHeight: 500,
    title: "Shelf",
    backgroundColor: "#1a1d24",
    autoHideMenuBar: true,
    icon: path.join(__dirname, "icon.svg"),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      // Keep the clock running while minimised: crossfades and Mix are timed by the page.
      backgroundThrottling: false,
    },
  });
  if (saved?.maximized) win.maximize();

  const remember = () => {
    if (!win || win.isMinimized()) return;
    writeSettings({ bounds: { ...(win.isMaximized() ? readSettings().bounds : win.getBounds()), maximized: win.isMaximized() } });
  };
  win.on("close", remember);

  // Links to anywhere else (Wikipedia, YouTube, MusicBrainz) open in the browser.
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:/i.test(url)) shell.openExternal(url);
    return { action: "deny" };
  });
  win.webContents.on("will-navigate", (e, url) => {
    const origin = serverOrigin();
    if (url.startsWith("file:") || (origin && url.startsWith(origin))) return;
    e.preventDefault();
    if (/^https?:/i.test(url)) shell.openExternal(url);
  });
  // The server can't be reached: back to the start screen, saying so.
  win.webContents.on("did-fail-load", (_e, code, _desc, url, isMainFrame) => {
    if (!isMainFrame || code === -3 || url.startsWith("file:")) return; // -3: a load replaced by another
    showStart(`Couldn’t reach ${(readSettings().server || "").replace(/^https?:\/\//, "")}. Is the server running? Try again, or enter another address.`);
  });
  openServer();
}

function buildMenu() {
  // The menu bar stays hidden (Alt shows it); its shortcuts work either way.
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    { label: "Shelf", submenu: [
      { label: "Change server…", click: () => showStart() },
      { type: "separator" },
      { role: "quit" },
    ] },
    { label: "View", submenu: [
      { role: "reload" },
      { role: "togglefullscreen" },
      { type: "separator" },
      { role: "zoomIn" }, { role: "zoomOut" }, { role: "resetZoom" },
      { type: "separator" },
      { role: "toggleDevTools" },
    ] },
  ]));
}

ipcMain.handle("shelf:connect", async (_e, input) => {
  const url = normalize(input);
  if (!url) return "That doesn’t look like a server address. Try something like 192.168.1.20:4533.";
  const problem = await check(url);
  if (problem) return problem;
  writeSettings({ server: url });
  win.loadURL(`${url}/`);
  return null;
});
ipcMain.on("shelf:change-server", () => showStart());
ipcMain.on("shelf:signed-in", (_e, name) => win?.setTitle(name ? `Shelf (${name})` : "Shelf"));

// One Shelf at a time: opening it again brings the window forward.
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (!win) return;
    if (win.isMinimized()) win.restore();
    win.focus();
  });
  app.whenReady().then(() => {
    // Microphone (voice requests) and notifications; nothing else the page asks for.
    session.defaultSession.setPermissionRequestHandler((_wc, permission, done) => {
      done(["media", "notifications", "fullscreen", "clipboard-sanitized-write", "mediaKeySystem"].includes(permission));
    });
    buildMenu();
    createWindow();
    updater.start();
  });
  app.on("window-all-closed", () => app.quit());
}
