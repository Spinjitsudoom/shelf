"""Backups of the database: what a rescan can't rebuild (likes, playlists, play history, accounts)."""

import gzip
import sqlite3
import time

from fastapi.testclient import TestClient

from shelf import backups
from shelf.db import init_db, session

DAY = 86400


def make_db(path, plays=0):
    init_db(path)
    with session(path) as conn:
        for i in range(plays):
            conn.execute("INSERT INTO meta(key, value) VALUES(?, ?)", (f"k{i}", "v"))
    return path


def count_meta(path):
    with sqlite3.connect(path) as conn:
        return conn.execute("SELECT COUNT(*) FROM meta").fetchone()[0]


def test_a_backup_is_a_whole_compressed_copy(tmp_path):
    db = make_db(tmp_path / "library.db", plays=3)
    b = backups.Backups(db, lambda: tmp_path / "backups")
    made = b.make(now=1_700_000_000)
    assert made.name.endswith(".db.gz") and made.parent == tmp_path / "backups"
    (tmp_path / "copy.db").write_bytes(gzip.decompress(made.read_bytes()))
    assert count_meta(tmp_path / "copy.db") == count_meta(db)
    assert [x["name"] for x in b.list()] == [made.name]


def test_one_a_day_is_due():
    assert backups.due([], now=1000) is True
    assert backups.due([1000], now=1000 + DAY - 7200) is False
    assert backups.due([1000], now=1000 + DAY) is True


def test_kept_a_week_of_days_and_two_months_of_weeks():
    now = 1_700_000_000
    times = [now - d * DAY for d in range(120)]  # one a day for four months
    kept = backups.to_keep(times, now=now)
    assert all(now - d * DAY in kept for d in range(7))
    older = sorted(t for t in kept if t < now - 6 * DAY)
    assert len(older) == 8  # one for each of the 8 weeks before
    assert all(b - a >= 6 * DAY for a, b in zip(older, older[1:]))
    assert min(kept) > now - 70 * DAY
    assert backups.to_keep([now - 400 * DAY], now=now) == {now - 400 * DAY}  # the only one: never thrown away


def test_old_backups_are_pruned_when_making_one(tmp_path):
    db = make_db(tmp_path / "library.db")
    b = backups.Backups(db, lambda: tmp_path / "backups")
    now = 1_700_000_000
    for d in range(30, 0, -1):
        b.make(now=now - d * DAY)
    b.make(now=now)
    assert 7 <= len(b.list()) <= 7 + 8


def test_restore_brings_the_old_data_back_and_keeps_todays(tmp_path):
    db = make_db(tmp_path / "library.db", plays=2)
    b = backups.Backups(db, lambda: tmp_path / "backups")
    old = b.make(now=time.time() - 3600)
    with session(db) as conn:
        conn.execute("INSERT INTO meta(key, value) VALUES('later', 'x')")
    before = count_meta(db)
    b.restore(old.name)
    assert count_meta(db) == before - 1
    safety = [x for x in b.list() if x["name"] != old.name]
    assert len(safety) == 1  # what was there just before, in case the restore was a mistake


def test_restore_refuses_names_that_are_not_backups(tmp_path):
    db = make_db(tmp_path / "library.db")
    b = backups.Backups(db, lambda: tmp_path / "backups")
    (tmp_path / "backups").mkdir()
    (tmp_path / "backups" / "shelf-broken.db.gz").write_bytes(gzip.compress(b"not a database"))
    for name in ("../library.db", "nope.db.gz", "shelf-broken.db.gz"):
        try:
            b.restore(name)
        except backups.BackupError:
            pass
        else:
            raise AssertionError(name)


def login(c, username="admin", password="hunter2"):
    assert c.post("/api/login", json={"username": username, "password": password}).status_code == 200


def test_admin_backs_up_downloads_and_restores(client, tmp_path):
    login(client)
    assert client.get("/api/admin/backups").json()["backups"] == []
    made = client.post("/api/admin/backups").json()
    name = made["name"]
    listing = client.get("/api/admin/backups").json()
    assert [x["name"] for x in listing["backups"]] == [name] and listing["folder"]
    r = client.get(f"/api/admin/backups/{name}")
    assert r.status_code == 200 and gzip.decompress(r.content)[:15] == b"SQLite format 3"
    assert client.get("/api/admin/backups/..%2Fsecret.key").status_code == 404

    pid = client.post("/api/playlists", json={"name": "Made after"}).json()["id"]
    assert client.post(f"/api/admin/backups/{name}/restore").status_code == 200
    assert client.get(f"/api/playlists/{pid}").status_code == 404  # back as it was
    assert client.get("/api/session").json()["user"]["username"] == "admin"  # still signed in

    elsewhere = tmp_path / "other-drive"
    elsewhere.mkdir()
    assert client.patch("/api/admin/backups", json={"folder": str(elsewhere)}).json()["folder"] == str(elsewhere)
    client.post("/api/admin/backups")
    assert len(list(elsewhere.glob("*.db.gz"))) == 1
    assert client.patch("/api/admin/backups", json={"folder": str(tmp_path / "missing")}).status_code == 400


def test_backups_are_admin_only(client):
    login(client)
    client.post("/api/users", json={"username": "sam", "password": "sam-pass"})
    sam = TestClient(client.app)
    login(sam, "sam", "sam-pass")
    assert sam.get("/api/admin/backups").status_code == 403
    assert sam.post("/api/admin/backups").status_code == 403
