import io
import json

from shelf import __version__, updates


def login(client):
    assert client.post("/api/login", json={"password": "hunter2"}).status_code == 200


def fake_release(monkeypatch, tag, assets=()):
    body = {"tag_name": tag, "html_url": f"https://github.com/x/releases/tag/{tag}", "body": "notes",
            "assets": [{"name": n, "browser_download_url": f"https://example.invalid/{n}"} for n in assets]}

    class Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(updates, "_get", lambda url, timeout=20: Resp(json.dumps(body).encode()))


def test_versions_compare_as_numbers():
    assert updates.parse("v0.10.2") == (0, 10, 2)
    assert updates.parse("1.2.3-beta") == (1, 2, 3)
    assert updates.newer("v0.10.0", "0.9.9")
    assert not updates.newer("v0.6.0", "0.6.0")
    assert not updates.newer("v0.5.9", "0.6.0")


def test_check_finds_a_newer_release(monkeypatch):
    fake_release(monkeypatch, "v99.0.0", ["Shelf-Server-Setup-99.0.0.exe"])
    u = updates.Updates()
    info = u.check()
    assert info["available"] and info["latest"] == "99.0.0" and info["current"] == __version__
    assert info["url"].endswith("v99.0.0") and info["error"] is None
    fake_release(monkeypatch, f"v{__version__}")
    assert not u.check()["available"]


def test_check_survives_being_offline(monkeypatch):
    def offline(url, timeout=20):
        raise OSError("no network")
    monkeypatch.setattr(updates, "_get", offline)
    info = updates.Updates().check()
    assert not info["available"] and "no network" in info["error"]


def test_admin_update_endpoints(client, monkeypatch):
    login(client)
    fake_release(monkeypatch, f"v{__version__}")
    r = client.post("/api/admin/update/check").json()
    assert r["available"] is False
    assert client.post("/api/admin/update").status_code == 409  # nothing newer
    assert "update" in client.get("/api/admin/overview").json()

    fake_release(monkeypatch, "v99.0.0")
    assert client.post("/api/admin/update/check").json()["available"] is True
    calls = []
    monkeypatch.setattr(updates.Updates, "_update_git", lambda self, restart: calls.append("git") or "Updated.")
    monkeypatch.setattr(updates.Updates, "_update_script", lambda self: calls.append("script") or "Updating.")
    monkeypatch.setattr(updates.Updates, "_update_windows", lambda self: calls.append("windows") or "Updating.")
    r = client.post("/api/admin/update")
    kind = client.get("/api/admin/overview").json()["update"]["kind"]
    if kind == "manual":
        assert r.status_code == 409
    else:
        assert r.status_code == 200 and calls == [kind]
        assert client.post("/api/admin/update").status_code == 409  # already updating


def test_git_checkout_pulls_and_restarts(tmp_path, monkeypatch):
    import subprocess

    def git(cwd, *args):
        subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                       check=True, capture_output=True)
    origin, work = tmp_path / "origin", tmp_path / "work"
    git(tmp_path, "init", "-q", "-b", "main", str(origin))
    (origin / "a.txt").write_text("1")
    git(origin, "add", ".")
    git(origin, "commit", "-qm", "one")
    git(tmp_path, "clone", "-q", str(origin), str(work))
    (origin / "a.txt").write_text("2")
    git(origin, "commit", "-qam", "two")

    monkeypatch.setattr(updates, "ROOT", work)
    monkeypatch.setattr(updates.shutil, "which", lambda name: "/usr/bin/git" if name == "git" else None)  # no uv here
    u = updates.Updates()
    assert u.state["kind"] == "git"
    u.state["available"] = True
    restarted = []
    monkeypatch.setattr(updates.threading, "Timer", lambda delay, fn: type("T", (), {"start": lambda self: restarted.append(fn)})())
    assert "restarting" in u.update(lambda: None)
    assert (work / "a.txt").read_text() == "2" and len(restarted) == 1

    # A copy with its own changes isn't touched.
    (work / "a.txt").write_text("mine")
    u2 = updates.Updates()
    u2.state["available"] = True
    try:
        u2.update(lambda: None)
        raise AssertionError("should refuse")
    except ValueError as e:
        assert "changes of its own" in str(e)
    assert not u2.state["updating"]


HOUR = 3600


def test_installs_only_when_quiet_and_at_night():
    t = 1_000_000.0
    quiet = updates.should_install
    assert quiet(hour=3, idle=45 * 60, pending=HOUR)  # night, nothing played for 45 minutes
    assert not quiet(hour=3, idle=10 * 60, pending=HOUR)  # someone's still listening
    assert not quiet(hour=15, idle=5 * HOUR, pending=HOUR)  # quiet, but daytime
    assert quiet(hour=15, idle=45 * 60, pending=4 * 24 * HOUR)  # no quiet night in three days: when it's quiet
    assert not quiet(hour=15, idle=5 * 60, pending=4 * 24 * HOUR)  # but never while music plays


def test_auto_update_step(monkeypatch, tmp_path):
    from shelf.db import init_db
    db = tmp_path / "x.db"
    init_db(db)
    fake_release(monkeypatch, "v99.0.0")
    last_play = [0.0]
    u = updates.Updates(db_path=db, idle_since=lambda: last_play[0])
    u.state["kind"] = "windows"
    started = []
    monkeypatch.setattr(updates.Updates, "update", lambda self, restart: started.append(1) or "Updating.")
    u.check()
    night = lambda h: __import__("datetime").datetime(2026, 11, 11, h, 30).timestamp()

    last_play[0] = night(3) - 5 * 60
    u.auto_step(night(3))
    assert started == []  # music five minutes ago
    last_play[0] = night(2) - HOUR
    u.auto_step(night(3))
    assert started == [1]  # quiet night: installed

    u.set_auto(False)
    started.clear()
    u.auto_step(night(4))
    assert started == [] and u.info()["auto"] is False


def test_auto_update_is_on_for_installed_copies(tmp_path):
    from shelf.db import init_db
    db = tmp_path / "x.db"
    init_db(db)
    u = updates.Updates(db_path=db)
    u.state["kind"] = "windows"
    assert u.auto() is True
    u.state["kind"] = "git"
    assert u.auto() is False  # a developer's checkout: only when asked
    u.set_auto(True)
    assert u.auto() is True


def test_admin_auto_update_switch(client):
    login(client)
    assert client.patch("/api/admin/update/auto", json={"enabled": True}).json()["auto"] is True
    assert client.get("/api/admin/overview").json()["update"]["auto"] is True
    assert client.patch("/api/admin/update/auto", json={"enabled": False}).json()["auto"] is False
