"""Signing in through a reverse proxy (Authelia, Authentik...), believed only from the proxy."""

from fastapi.testclient import TestClient

from shelf.app import create_app
from shelf.config import Config
from shelf.proxyauth import wrap


def make(tmp_path, library, trusted):
    cfg = Config(music_dirs=[library], data_dir=tmp_path / "data", password="hunter2", online_lyrics=False,
                 music_videos=False, artist_info=False, analyze_tempo=False,
                 proxy_user_header="Remote-User", proxy_trusted=trusted)
    app = create_app(cfg, start_scanner=False)
    app.state.scanner.run_once()
    return app


def test_the_proxy_signs_people_in(tmp_path, library):
    app = make(tmp_path, library, ["10.0.0.0/8"])
    proxy = TestClient(app, client=("10.1.2.3", 5000))
    s = proxy.get("/api/session", headers={"Remote-User": "sam"}).json()
    assert s["signedIn"] and s["user"]["username"] == "sam" and s["user"]["admin"] is False  # a new account
    assert proxy.get("/api/albums", headers={"Remote-User": "sam"}).status_code == 200
    assert proxy.get("/api/session", headers={"Remote-User": "admin"}).json()["user"]["admin"] is True
    assert proxy.get("/api/albums").status_code == 401  # no header: nobody
    # Subsonic apps behind the proxy, sending no password of their own.
    r = proxy.get("/rest/ping", params={"f": "json"}, headers={"Remote-User": "sam"}).json()["subsonic-response"]
    assert r["status"] == "ok"

    # Anyone else sending the header is ignored.
    outsider = TestClient(app, client=("192.168.1.50", 5000))
    assert outsider.get("/api/albums", headers={"Remote-User": "admin"}).status_code == 401
    assert outsider.get("/api/session", headers={"Remote-User": "admin"}).json()["signedIn"] is False


def test_the_real_connection_counts_not_x_forwarded_for(tmp_path, library):
    app = make(tmp_path, library, ["10.0.0.0/8"])
    # From outside, claiming to come from the proxy's network: still outside.
    served = wrap(app, "*")
    c = TestClient(served, client=("203.0.113.9", 5000))
    r = c.get("/api/albums", headers={"Remote-User": "admin", "X-Forwarded-For": "10.0.0.1"})
    assert r.status_code == 401
    # Through the proxy, the visitor's own address is what Shelf sees (for the password lockout).
    p = TestClient(served, client=("10.0.0.2", 5000))
    assert p.get("/api/albums", headers={"Remote-User": "admin", "X-Forwarded-For": "203.0.113.9"}).status_code == 200


def test_off_without_trusted_addresses(tmp_path, library):
    app = make(tmp_path, library, [])
    c = TestClient(app, client=("10.1.2.3", 5000))
    assert c.get("/api/albums", headers={"Remote-User": "admin"}).status_code == 401


def test_email_names_and_connect(tmp_path, library):
    from shelf.proxyauth import shelf_name

    assert shelf_name("alice@example.com") == "alice_example.com"
    assert shelf_name("  Sam Smith ") == "Sam Smith" and shelf_name("@@@") == ""
    app = make(tmp_path, library, ["10.0.0.0/8"])
    proxy = TestClient(app, client=("10.1.2.3", 5000))
    s = proxy.get("/api/session", headers={"Remote-User": "alice@example.com"}).json()
    assert s["signedIn"] and s["user"]["username"] == "alice_example.com"
    again = proxy.get("/api/session", headers={"Remote-User": "alice@example.com"}).json()
    assert again["user"]["id"] == s["user"]["id"]  # the same account every time
    with proxy.websocket_connect("/api/connect", headers={"Remote-User": "alice@example.com", "Origin": "http://testserver"}) as ws:
        ws.send_json({"type": "hello", "name": "Test", "kind": "web"})
