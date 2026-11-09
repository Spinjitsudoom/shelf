// Which Shelf server this app talks to.
//
// In a browser, the app is the server's own page, so changing server means going to the
// other server's address. In the Android or desktop app, the page asks the app around it
// (window.ShelfAndroid or window.ShelfDesktop) to remember the new address and open it.

/** The Android or desktop app this page runs in, or null in a browser. */
export const nativeApp = window.ShelfAndroid ?? window.ShelfDesktop ?? null;

/** This server's address as people type it, e.g. "http://192.168.1.20:4533". */
export function currentServer() {
  return new URL(".", location.href).href.replace(/\/$/, "");
}

/** What was typed ("192.168.1.20:4533", "shelf.home/") as a full address, or null. */
export function normalizeServer(input) {
  let s = (input || "").trim();
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

/** Checks a Shelf server answers at `url`. Throws an Error with a message to show if not. */
export async function checkServer(url) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 7000);
  let res;
  try {
    res = await fetch(`${url}/api/ping`, { cache: "no-store", credentials: "omit", signal: ctl.signal });
  } catch {
    const blocked = location.protocol === "https:" && url.startsWith("http:");
    throw new Error(blocked
      ? "This page is on https, so it can’t open an http server. Open that address in the browser instead."
      : `Couldn’t reach ${url}. Check the address, and that the server is running and on the same network.`);
  } finally {
    clearTimeout(timer);
  }
  const body = res.ok ? await res.json().catch(() => null) : null;
  if (body?.app !== "shelf") throw new Error(`${url} answered, but it isn’t a Shelf server.`);
  return body;
}

/** Go to another server (after checking it's there). Resolves false if it's this one. */
export async function switchServer(input) {
  const url = normalizeServer(input);
  if (!url) throw new Error("That doesn’t look like a server address. Try something like 192.168.1.20:4533.");
  if (url === currentServer()) return false;
  await checkServer(url);
  if (nativeApp) nativeApp.setServer(url);
  else location.href = `${url}/`;
  return true;
}
