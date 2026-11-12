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


def test_measuring_gives_way(client):
    db = client.app.state.cfg.db_path
    hour = [14]
    clock = lambda: time.struct_time((2026, 11, 12, hour[0], 0, 0, 3, 316, 0))  # noqa: E731
    stop, wake = threading.Event(), threading.Event()
    turn = background.Turn(db, stop, wake, minutes=15, clock=clock)
    assert not turn.is_set()  # any time, by default
    background.set_mode(db, "night")
    turn = background.Turn(db, stop, wake, minutes=15, clock=clock)
    assert turn.is_set()  # two in the afternoon: not now
    hour[0] = 2
    turn = background.Turn(db, stop, wake, minutes=15, clock=clock)
    assert not turn.is_set()  # two at night: go
    wake.set()
    assert turn.is_set()  # a scan is wanted: make way
    wake.clear()
    assert background.Turn(db, stop, wake, minutes=0, clock=clock).is_set()  # time's up: the regular rescan
    stop.set()
    assert turn.is_set()


def test_a_rescan_is_not_held_up(client):
    """While songs wait to be measured outside their hours, scans still run."""
    db = client.app.state.cfg.db_path
    background.set_mode(db, "never")
    with session(db) as conn:
        conn.execute("UPDATE tracks SET loud_checked = 0")
    t = threading.Thread(target=client.app.state.scanner.run_once)
    t.start()
    t.join(5)
    assert not t.is_alive()


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
