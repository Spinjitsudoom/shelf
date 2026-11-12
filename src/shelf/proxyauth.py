"""Signing in through a reverse proxy that already knows who you are: Authelia, Authentik,
oauth2-proxy, Caddy's forward_auth and the like put the signed-in person's name in a header
(Remote-User, X-Forwarded-User...), and Shelf takes their word for it.

Only from the proxy itself: the header is believed only when the connection comes from an
address the admin listed (proxy_trusted), because anyone else could send it too. Someone Shelf
hasn't met yet gets an account of their own (an admin, if they're the very first).

The address a connection really comes from is noted before X-Forwarded-For is applied (which
replaces it with the visitor's): see wrap().
"""

from __future__ import annotations

import ipaddress
import logging
import secrets

log = logging.getLogger("shelf.proxyauth")

PEER = "shelf.peer"


class _NotePeer:
    """Keeps the connecting address in the request, before anything rewrites it."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            client = scope.get("client")
            scope[PEER] = client[0] if client else None
        await self.app(scope, receive, send)


def wrap(app, forwarded_allow_ips: str):
    """The app as the server runs it: the peer noted, then X-Forwarded-For/-Proto applied for
    the proxies in FORWARDED_ALLOW_IPS (uvicorn's own handling of them)."""
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    return _NotePeer(ProxyHeadersMiddleware(app, trusted_hosts=forwarded_allow_ips))


def networks(values) -> list:
    out = []
    for v in values or []:
        v = str(v).strip()
        if not v:
            continue
        try:
            out.append(ipaddress.ip_network(v, strict=False))
        except ValueError:
            log.warning("proxy_trusted: %r isn't an address or a network, so it's left out", v)
    return out


def _peer(request) -> str | None:
    if PEER in request.scope:
        return request.scope[PEER]
    return request.client.host if request.client else None


class ProxyAuth:
    def __init__(self, auth, header: str, trusted: list):
        self.auth, self.header, self.trusted = auth, (header or "").strip(), networks(trusted)
        if self.header and not self.trusted:
            log.warning("proxy_user_header is set but proxy_trusted isn't: nobody is signed in from the header")

    @property
    def on(self) -> bool:
        return bool(self.header and self.trusted)

    def from_proxy(self, request) -> bool:
        peer = _peer(request)
        try:
            ip = ipaddress.ip_address(peer) if peer else None
        except ValueError:
            return False
        return ip is not None and any(ip in n for n in self.trusted)

    def user_for(self, request):
        """The person the proxy says this is, or None."""
        if not self.on:
            return None
        name = (request.headers.get(self.header) or "").strip()
        if not name or not self.from_proxy(request):
            return None
        row = self.auth.find(name)
        if row is None:
            try:
                first = not self.auth.has_users()
                user = self.auth.create(name, secrets.token_urlsafe(24), admin=first, check=False)
                log.info("Made an account for %s, signed in by the proxy", name)
                return user
            except ValueError as e:  # made by another request a moment ago, or a name Shelf can't use
                row = self.auth.find(name)
                if row is None:
                    log.warning("The proxy signed in %r, but %s", name, e)
                    return None
        return self.auth.get(row["id"])
