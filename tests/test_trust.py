"""https trusts Mozilla's authorities as well as the computer's own (Windows lacks newer ones)."""

import ssl

import certifi

from shelf import trust


def test_mozillas_authorities_are_trusted(monkeypatch):
    monkeypatch.setattr(ssl, "_create_default_https_context", ssl._create_default_https_context)
    monkeypatch.setattr(trust, "_installed", False)
    trust.install()
    assert ssl._create_default_https_context is trust.context
    ctx = ssl._create_default_https_context()
    assert ctx is trust.context()  # one shared context
    bundled = ssl.create_default_context(cafile=certifi.where()).cert_store_stats()["x509_ca"]
    assert ctx.cert_store_stats()["x509_ca"] >= bundled > 50
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
