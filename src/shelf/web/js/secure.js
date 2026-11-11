// Moving to the server's secure (https) address (see src/shelf/secure.py).
//
// When the server has one and this page was opened over plain http from the internet, the page
// moves there, carrying its sign-in over with a one-time code: a browser keeps sign-ins per
// address, so otherwise everyone would have to type their password again. At home (a private
// address) nothing changes. The Android and desktop apps move by themselves, so inside them the
// page leaves it to them.

import { nativeApp } from "./server.js";

const PRIVATE_SUFFIXES = [".local", ".lan", ".home", ".internal", ".home.arpa", ".ts.net"];

/** At home or on the tailnet: loopback, LAN, Tailscale's 100.64/10, bare names, .local and such. */
export function isPrivate(host) {
  host = host.toLowerCase().replace(/^\[|\]$/g, "").replace(/\.$/, "");
  const v4 = host.match(/^(\d+)\.(\d+)\.(\d+)\.(\d+)$/);
  if (v4) {
    const [a, b] = [Number(v4[1]), Number(v4[2])];
    return a === 10 || a === 127 || a === 0 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168)
      || (a === 169 && b === 254) || (a === 100 && b >= 64 && b <= 127);
  }
  if (host.includes(":")) return host === "::1" || /^f[cd]/.test(host) || /^fe[89ab]/.test(host);
  return host === "localhost" || !host.includes(".") || PRIVATE_SUFFIXES.some((s) => host.endsWith(s));
}

/** On the secure address, just moved here: trade the code for a sign-in, and go back to where the
 * page was. Call before anything asks the server who's signed in. */
export async function claimHandoff() {
  const m = location.hash.match(/^#handoff=([\w-]+)(?:&to=(.*))?$/);
  if (!m) return;
  history.replaceState(null, "", location.pathname + location.search + (m[2] ? decodeURIComponent(m[2]) : ""));
  await fetch("api/session/claim", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code: m[1] }),
  }).catch(() => {});
}

/** Moves the page to the secure address when it should. True if it's leaving. */
export async function moveToSecure(session) {
  const to = session?.secureUrl;
  if (!to || nativeApp || location.protocol !== "http:" || isPrivate(location.hostname)) return false;
  if (new URL(to).hostname === location.hostname) return false;
  let code = "";
  if (session.signedIn) {
    const r = await fetch("api/session/handoff", { method: "POST" }).catch(() => null);
    code = r?.ok ? (await r.json()).code : "";
  }
  const back = encodeURIComponent(location.hash);
  location.replace(code ? `${to}/#handoff=${code}&to=${back}` : `${to}/${location.hash}`);
  return true;
}
