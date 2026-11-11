"""A secure (https) address: Tailscale Funnel or the admin's own, which apps and browsers move to."""

import json
import os
import stat
import sys
import time

from fastapi.testclient import TestClient

from shelf import secure

SECURE = "https://shelf-pc.example.ts.net"


def login(c, username="admin", password="hunter2"):
    r = c.post("/api/login", json={"username": username, "password": password})
    assert r.status_code == 200
    return r.json()["token"]


def test_addresses_are_cleaned_up_and_must_be_https():
    assert secure.normalize("https://shelf-pc.example.ts.net/") == SECURE
    assert secure.normalize("shelf-pc.example.ts.net") == SECURE
    assert secure.normalize(" https://music.example.org:8443 ") == "https://music.example.org:8443"
    assert secure.normalize("http://music.example.org") is None
    assert secure.normalize("https://music.example.org/shelf") is None  # Shelf lives at the root
    assert secure.normalize("") is None
    assert secure.normalize("https://") is None


def test_home_and_tailnet_addresses_count_as_private():
    for host in ["localhost", "127.0.0.1", "192.168.0.64", "10.0.0.5", "172.20.1.1", "100.64.132.58",
                 "desktop-apr1r4t", "nas.local", "::1", "fd7a:115c:a1e0::1", "169.254.3.4"]:
        assert secure.is_private(host), host
    for host in ["77.71.156.41", "8.8.8.8", "172.32.0.1", "music.duckdns.org", "2a00:1450::1"]:
        assert not secure.is_private(host), host


def test_only_plain_http_from_the_internet_is_sent_to_the_secure_address():
    assert secure.redirect_for("http", "77.71.156.41:4533", "/", "", SECURE) == SECURE + "/"
    assert secure.redirect_for("http", "77.71.156.41:4533", "/s/abc", "x=1", SECURE) == SECURE + "/s/abc?x=1"
    assert secure.redirect_for("https", "77.71.156.41", "/", "", SECURE) is None
    assert secure.redirect_for("http", "192.168.0.64:4533", "/", "", SECURE) is None  # at home
    assert secure.redirect_for("http", "shelf-pc.example.ts.net", "/", "", SECURE) is None
    assert secure.redirect_for("http", "77.71.156.41:4533", "/", "", None) is None
    assert secure.redirect_for("http", "[2a00:1450::1]:4533", "/", "", SECURE) == SECURE + "/"


def test_reads_tailscales_name_and_whether_funnel_serves_shelf():
    status = {"BackendState": "Running", "Self": {"DNSName": "shelf-pc.example.ts.net."}}
    assert secure.name_from_status(status) == "shelf-pc.example.ts.net"
    assert secure.name_from_status({"BackendState": "Stopped", "Self": {"DNSName": "x.ts.net."}}) is None
    assert secure.name_from_status({}) is None

    host = "shelf-pc.example.ts.net:443"
    on = {"TCP": {"443": {"HTTPS": True}}, "Web": {host: {"Handlers": {"/": {"Proxy": "http://127.0.0.1:4533"}}}},
          "AllowFunnel": {host: True}}
    assert secure.funnel_serves(on, "shelf-pc.example.ts.net", 4533)
    assert not secure.funnel_serves(on, "shelf-pc.example.ts.net", 4534)
    assert not secure.funnel_serves({**on, "AllowFunnel": {}}, "shelf-pc.example.ts.net", 4533)  # tailnet only
    assert not secure.funnel_serves({}, "shelf-pc.example.ts.net", 4533)


def fake_tailscale(tmp_path, funnel_script: str):
    """A stand-in `tailscale` program: `status --json` says who it is, `funnel` does what it's told."""
    exe = tmp_path / "tailscale"
    exe.write_text(f"""#!{sys.executable}
import json, sys, time
args = sys.argv[1:]
if args[:2] == ["status", "--json"]:
    print(json.dumps({{"BackendState": "Running", "Self": {{"DNSName": "shelf-pc.example.ts.net."}}}}))
elif args[:1] == ["funnel"]:
{funnel_script}
""")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return str(exe)


def test_turning_funnel_on_reports_the_address(tmp_path):
    exe = fake_tailscale(tmp_path, "    print('Available on the internet: https://shelf-pc.example.ts.net/')")
    assert secure.start_funnel(exe, 4533) == {"ok": True, "url": SECURE}


def test_funnel_not_allowed_yet_gives_the_link_to_allow_it(tmp_path):
    exe = fake_tailscale(tmp_path, "    print('Funnel is not enabled on your tailnet.\\nTo enable, visit:\\n\\n"
                                   "         https://login.tailscale.com/f/funnel?node=abc123', flush=True)\n"
                                   "    time.sleep(30)")
    t = time.monotonic()
    got = secure.start_funnel(exe, 4533, wait=2)
    assert time.monotonic() - t < 10
    assert got == {"ok": False, "allow": "https://login.tailscale.com/f/funnel?node=abc123"}


def test_funnel_failing_says_why(tmp_path):
    exe = fake_tailscale(tmp_path, "    print('Access denied: serve config denied', file=sys.stderr); sys.exit(1)")
    got = secure.start_funnel(exe, 4533)
    assert got["ok"] is False and "denied" in got["error"]


def test_handoff_codes_work_once_and_run_out():
    h = secure.Handoffs(ttl=60)
    code = h.make(7, now=1000)
    assert len(code) >= 32
    assert h.claim(code, now=1010) == 7
    assert h.claim(code, now=1011) is None  # once only
    late = h.make(7, now=1000)
    assert h.claim(late, now=1061) is None
    assert h.claim("made-up", now=1000) is None


# ---------- through the server ----------

def set_secure(client, url=SECURE, monkeypatch=None):
    if monkeypatch:
        monkeypatch.setattr(secure, "reaches", lambda url: True)
    return client.put("/api/admin/secure", json={"url": url})


def test_admin_sets_the_secure_address_and_everyone_is_told(client, monkeypatch):
    login(client)
    assert client.get("/api/session").json()["secureUrl"] is None
    monkeypatch.setattr(secure, "reaches", lambda url: False)
    r = client.put("/api/admin/secure", json={"url": SECURE})
    assert r.status_code == 400 and "reach" in r.json()["detail"]
    assert client.put("/api/admin/secure", json={"url": "http://plain.example.org"}).status_code == 400
    r = set_secure(client, monkeypatch=monkeypatch)
    assert r.status_code == 200 and r.json()["url"] == SECURE
    assert TestClient(client.app).get("/api/session").json()["secureUrl"] == SECURE
    assert client.put("/api/admin/secure", json={"url": None}).json()["url"] is None


def test_only_admins_change_it(client, monkeypatch):
    login(client)
    client.post("/api/users", json={"username": "kim", "password": "longenough1"})
    other = TestClient(client.app)
    login(other, "kim", "longenough1")
    monkeypatch.setattr(secure, "reaches", lambda url: True)
    assert other.put("/api/admin/secure", json={"url": SECURE}).status_code == 403
    assert other.get("/api/admin/secure").status_code == 403


def test_sign_in_page_over_plain_http_from_the_internet_moves_to_the_secure_address(client, monkeypatch):
    login(client)
    set_secure(client, monkeypatch=monkeypatch)
    guest = TestClient(client.app, base_url="http://77.71.156.41:4533")
    r = guest.get("/", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == SECURE + "/"
    # The API isn't redirected (older apps would lose their sign-in on the way), nor the Subsonic one.
    assert guest.get("/api/ping", follow_redirects=False).status_code == 200
    # At home, or already on the secure address: nothing changes.
    assert TestClient(client.app, base_url="http://192.168.0.64:4533").get("/", follow_redirects=False).status_code == 200
    assert TestClient(client.app, base_url=SECURE).get("/", follow_redirects=False).status_code == 200


def test_signed_in_browsers_are_left_for_the_web_app_to_move_with_their_sign_in(client, monkeypatch):
    login(client)
    set_secure(client, monkeypatch=monkeypatch)
    browser = TestClient(client.app, base_url="http://77.71.156.41:4533")
    login(browser)
    assert browser.get("/", follow_redirects=False).status_code == 200
    code = browser.post("/api/session/handoff").json()["code"]
    there = TestClient(client.app, base_url=SECURE)
    r = there.post("/api/session/claim", json={"code": code})
    assert r.status_code == 200 and r.json()["user"]["username"] == "admin"
    assert there.get("/api/albums").status_code == 200  # signed in there now
    assert TestClient(client.app, base_url=SECURE).post("/api/session/claim", json={"code": code}).status_code == 401
