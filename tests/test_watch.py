"""The watch folder: music dropped in is renamed from its tags and filed as Artist/Album."""

import os
import time

from conftest import make_track

from shelf import watch


def test_files_settled_songs_with_their_cover(tmp_path, cover_jpg):
    inbox, music = tmp_path / "inbox", tmp_path / "music"
    music.mkdir()
    make_track(inbox / "rip" / "track1.mp3", title="Riff Raff", artist="AC/DC", album="Powerage", track=4)
    (inbox / "rip" / "folder.jpg").write_bytes(cover_jpg.read_bytes())
    filed = []
    w = watch.Watcher(lambda: inbox, lambda: music, on_filed=filed.append, settle=0)

    assert w.tick() == 0  # first sight: wait until it stops changing
    assert w.tick() == 1
    song = music / "AC DC" / "Powerage" / "04 Riff Raff.mp3"
    assert song.exists() and (music / "AC DC" / "Powerage" / "folder.jpg").exists()
    assert not (inbox / "rip").exists()  # the emptied folder is tidied away
    assert inbox.exists() and filed == [1]


def test_a_file_still_being_copied_waits(tmp_path):
    inbox, music = tmp_path / "inbox", tmp_path / "music"
    music.mkdir()
    make_track(inbox / "a.mp3", title="One", artist="Band", album="Live", track=1)
    w = watch.Watcher(lambda: inbox, lambda: music, settle=0)
    w.tick()
    with open(inbox / "a.mp3", "ab") as f:  # still growing
        f.write(b"\0" * 1000)
    assert w.tick() == 0
    assert w.tick() == 1  # stopped changing: filed


def test_recent_files_wait_for_the_settle_time(tmp_path):
    inbox, music = tmp_path / "inbox", tmp_path / "music"
    music.mkdir()
    make_track(inbox / "a.mp3", title="One", artist="Band", album="Live", track=1)
    w = watch.Watcher(lambda: inbox, lambda: music, settle=60)
    w.tick(); assert w.tick() == 0  # written just now
    old = time.time() - 120
    os.utime(inbox / "a.mp3", (old, old))
    w.tick(); assert w.tick() == 1


def test_no_folder_set_does_nothing(tmp_path):
    w = watch.Watcher(lambda: None, lambda: tmp_path, settle=0)
    assert w.tick() == 0


def test_admin_sets_the_watch_folder(client, tmp_path):
    assert client.post("/api/login", json={"password": "hunter2"}).status_code == 200
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    r = client.patch("/api/admin/watch", json={"path": str(inbox)})
    assert r.status_code == 200 and r.json()["path"] == str(inbox)
    music = client.app.state.cfg.music_dirs[0]
    assert client.patch("/api/admin/watch", json={"path": str(music / "sub")}).status_code == 400  # inside the music
    assert client.patch("/api/admin/watch", json={"path": str(tmp_path / "missing")}).status_code == 400
    assert client.patch("/api/admin/watch", json={"path": ""}).json()["path"] is None  # off
