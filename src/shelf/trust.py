"""Which certificate authorities Shelf trusts for https: the computer's own, plus Mozilla's list
(certifi).

Python on Windows only knows the authorities Windows has already stored, and Windows stores
newer ones only when something like a browser asks for them, which Python never does. So a
Windows server could fail every https call to a site with a newer certificate chain, e.g. the
Cover Art Archive (Let's Encrypt's ISRG Root X2), while MusicBrainz (DigiCert) works fine.
Adding Mozilla's list fixes that everywhere, and keeps a company or home authority the computer
trusts working too.
"""

from __future__ import annotations

import logging
import ssl
import threading

log = logging.getLogger("shelf.trust")
_lock = threading.Lock()
_ctx: ssl.SSLContext | None = None
_installed = False


def context() -> ssl.SSLContext:
    """One shared context for https: the system's authorities and Mozilla's."""
    global _ctx
    with _lock:
        if _ctx is None:
            ctx = ssl.create_default_context()
            try:
                import certifi

                ctx.load_verify_locations(certifi.where())
            except (ImportError, OSError, ssl.SSLError) as e:  # the computer's own list still works
                log.warning("Couldn't add Mozilla's certificate list (%s); using the computer's own", e)
            _ctx = ctx
        return _ctx


def install() -> None:
    """Make every https call that doesn't bring its own context (urllib, http.client) use it."""
    global _installed
    if _installed:
        return
    ssl._create_default_https_context = context  # noqa: SLF001 - the documented hook for this
    _installed = True
