from fastapi.testclient import TestClient

from shelf.app import create_app
from shelf.config import Config


def login(client, username="admin", password="hunter2"):
    r = client.post("/api/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def test_config_password_makes_the_admin(client):
    s = client.get("/api/session").json()
    assert s["setup"] is False and s["signedIn"] is False
    me = login(client)["user"]
    assert me == {"id": 1, "username": "admin", "admin": True}
    assert client.get("/api/session").json()["user"]["admin"] is True
    # Older apps sign in with only the password.
    assert client.post("/api/login", json={"password": "hunter2"}).status_code == 200


def test_admin_adds_people_who_get_their_own_music(client):
    login(client)
    assert client.post("/api/users", json={"username": "sam", "password": "short"}).status_code == 400
    sam = client.post("/api/users", json={"username": "Sam", "password": "sam-pass"}).json()
    assert sam["admin"] is False
    assert client.post("/api/users", json={"username": "sam", "password": "another1"}).status_code == 400

    track = client.get("/api/albums").json()[0]
    tid = client.get(f"/api/albums/{track['id']}").json()["tracks"][0]["id"]
    client.put(f"/api/likes/{tid}")
    pid = client.post("/api/playlists", json={"name": "Admin's"}).json()["id"]
    client.post(f"/api/tracks/{tid}/played")

    with TestClient(client.app) as other:
        login(other, "sam", "sam-pass")
        assert other.get("/api/likes/ids").json() == []
        assert other.get("/api/playlists").json() == []
        assert other.get(f"/api/playlists/{pid}").status_code == 404
        assert other.delete(f"/api/playlists/{pid}").status_code == 404
        assert other.get("/api/home").json()["recent"] == []
        assert other.get("/api/users").status_code == 403
        assert other.post("/api/scan").status_code == 403
        other.put(f"/api/likes/{tid}")
        assert other.get("/api/likes/ids").json() == [tid]

    users = {u["username"]: u for u in client.get("/api/users").json()}
    assert users["admin"]["likes"] == 1 and users["admin"]["playlists"] == 1 and users["admin"]["plays"] == 1
    assert users["Sam"]["likes"] == 1
    assert client.get("/api/admin/overview").json()["library"]["tracks"] == 4


def test_password_changes_sign_out_other_devices(client):
    login(client)
    sam = client.post("/api/users", json={"username": "sam", "password": "sam-pass"}).json()
    with TestClient(client.app) as phone:
        token = login(phone, "sam", "sam-pass")["token"]
        # The Android app (or anything else) can use the token as a Bearer header.
        with TestClient(client.app) as bare:
            assert bare.get("/api/likes/ids", headers={"Authorization": f"Bearer {token}"}).status_code == 200
            assert client.patch(f"/api/users/{sam['id']}", json={"password": "new-pass"}).status_code == 200
            assert bare.get("/api/likes/ids", headers={"Authorization": f"Bearer {token}"}).status_code == 401
        assert phone.get("/api/likes/ids").status_code == 401
        login(phone, "sam", "new-pass")
        assert phone.put("/api/me/password", json={"current": "wrong", "new": "x" * 8}).status_code == 403
        assert phone.put("/api/me/password", json={"current": "new-pass", "new": "newer-pass"}).status_code == 200
        assert phone.get("/api/likes/ids").status_code == 200  # this device stays signed in


def test_admins_cant_lock_themselves_out(client):
    me = login(client)["user"]
    assert client.patch(f"/api/users/{me['id']}", json={"admin": False}).status_code == 409
    assert client.delete(f"/api/users/{me['id']}").status_code == 409
    sam = client.post("/api/users", json={"username": "sam", "password": "sam-pass", "admin": True}).json()
    assert client.delete(f"/api/users/{sam['id']}").status_code == 200
    with TestClient(client.app) as other:
        assert other.post("/api/login", json={"username": "sam", "password": "sam-pass"}).status_code == 401


def test_first_run_setup(tmp_path, library):
    cfg = Config(music_dirs=[library], data_dir=tmp_path / "fresh", online_lyrics=False, music_videos=False,
                 artist_info=False, analyze_tempo=False)
    app = create_app(cfg, start_scanner=False)
    with TestClient(app) as c:
        assert c.get("/api/session").json()["setup"] is True
        assert c.get("/api/library").status_code == 401
        r = c.post("/api/setup", json={"username": "Me", "password": "my-password"})
        assert r.status_code == 200 and r.json()["user"]["admin"] is True
        assert c.get("/api/library").status_code == 200
        assert c.post("/api/setup", json={"username": "Them", "password": "their-pass"}).status_code == 409
        assert c.get("/api/ping").headers["access-control-allow-origin"] == "*"


def test_offline_plays_keep_their_time(client):
    import time
    login(client)
    tid = client.get("/api/tracks/random?limit=1").json()[0]["id"]
    then = time.time() - 3 * 86400
    assert client.post(f"/api/tracks/{tid}/played?at={then}").status_code == 200
    assert client.post(f"/api/tracks/{tid}/played?at={time.time() + 9999}").status_code == 200  # future: now
    recent = client.get("/api/tracks/recent").json()
    assert abs(recent[0]["playedAt"] - time.time()) < 60


def test_admin_clears_signin_lockouts(client):
    login(client)
    for _ in range(8):
        client.post("/api/login", json={"username": "admin", "password": "wrong"})
    assert client.post("/api/login", json={"username": "admin", "password": "hunter2"}).status_code == 429
    s = client.get("/api/admin/signins").json()
    assert s[0]["locked"] is True and s[0]["attempts"] == 8 and s[0]["until"]
    assert client.get("/api/admin/overview").json()["signins"][0]["locked"] is True
    r = client.delete(f"/api/admin/signins?address={s[0]['address']}").json()
    assert r == {"cleared": 1, "left": []}
    assert client.post("/api/login", json={"username": "admin", "password": "hunter2"}).status_code == 200
    client.post("/api/login", json={"username": "admin", "password": "wrong"})
    assert client.delete("/api/admin/signins").json()["cleared"] == 1
