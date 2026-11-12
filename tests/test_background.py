"""When songs are measured in the background: any time, only at night, or never."""

import threading
import time

from shelf import background
from shelf.db import session


def login(c):
    assert c.post("/api/login", json={"username": "admin", "password": "hunter2"}).status_code == 200


def test_hours():
    assert background.allowed("always", 14)
    assert background.allowed("night", 3) and not background.allowed("night", 7) and not background.allowed("night", 0)
    assert not background.allowed("never", 3)


def test_the_gate_waits_for_its_hours(tmp_path, client):
    db = client.app.state.cfg.db_path
    background.set_mode(db, "night")
    hour = [14]
    clock = lambda: time.struct_time((2026, 11, 12, hour[0], 0, 0, 3, 316, 0))  # noqa: E731
    stop = threading.Event()
    gate = background.gate(db, stop, clock=clock, check_every=0.01)
    done = threading.Event()
    t = threading.Thread(target=lambda: (gate(), done.set()))
    t.start()
    assert not done.wait(0.1)  # two in the afternoon: waits
    hour[0] = 2
    assert done.wait(1)  # two at night: goes
    background.set_mode(db, "never")
    done.clear()
    t = threading.Thread(target=lambda: (gate(), done.set()))
    t.start()
    assert not done.wait(0.1)
    stop.set()  # the server stopping lets it go
    assert done.wait(1)


def test_admin_chooses(client):
    login(client)
    assert client.get("/api/admin/overview").json()["backgroundWork"] == "always"
    assert client.patch("/api/admin/background", json={"mode": "sometimes"}).status_code == 400
    assert client.patch("/api/admin/background", json={"mode": "never"}).json() == {"backgroundWork": "never"}
    assert client.get("/api/admin/overview").json()["backgroundWork"] == "never"
    # Never: a scan finds the songs but measures none of them.
    db = client.app.state.cfg.db_path
    with session(db) as conn:
        conn.execute("UPDATE tracks SET loud_checked = 0, lufs = NULL")
    client.app.state.scanner.run_once()
    with session(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM tracks WHERE loud_checked = 1").fetchone()[0] == 0
