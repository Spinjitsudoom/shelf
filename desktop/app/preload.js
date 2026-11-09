// What the desktop app offers the pages it shows, as window.ShelfDesktop. Shelf's web app
// uses it the way it uses the Android app's bridge: to change server, and to say who's signed in.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("ShelfDesktop", {
  /** Check `url` is a Shelf server, remember it and open it. Resolves to an error message, or null. */
  connect: (url) => ipcRenderer.invoke("shelf:connect", url),
  /** Same, for the web app's own server picker (it has already checked the server). */
  setServer: (url) => ipcRenderer.invoke("shelf:connect", url),
  /** Back to the start screen to type another server address. */
  changeServer: () => ipcRenderer.send("shelf:change-server"),
  signedIn: (name) => ipcRenderer.send("shelf:signed-in", String(name || "")),
});
