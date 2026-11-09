import shutil

from conftest import make_track


def login(client):
    assert client.post("/api/login", json={"password": "hunter2"}).status_code == 200


def test_add_change_and_remove_folders(client, tmp_path, monkeypatch):
    monkeypatch.delenv("SHELF_MUSIC_DIRS", raising=False)
    login(client)
    scan = client.app.state.scanner.run_once
    state = client.get("/api/folders").json()
    assert [f["tracks"] for f in state["folders"]] == [4] and state["locked"] is False

    extra = tmp_path / "more"
    make_track(extra / "Other" / "Solo" / "01 Song.mp3", title="Song", artist="Other", album="Solo", track=1)
    r = client.post("/api/folders", json={"path": str(extra)})
    assert r.status_code == 200, r.text
    scan()
    assert [f["tracks"] for f in client.get("/api/folders").json()["folders"]] == [4, 1]

    # Already there, inside a library folder, missing, or Shelf's own data: refused with a reason.
    assert "already" in client.post("/api/folders", json={"path": str(extra)}).json()["detail"]
    assert "inside" in client.post("/api/folders", json={"path": str(extra / "Other")}).json()["detail"]
    assert client.post("/api/folders", json={"path": str(tmp_path / "nope")}).status_code == 400
    assert client.post("/api/folders", json={"path": str(tmp_path / "data")}).status_code == 400

    # Moving the folder keeps the song (and so its like).
    song = next(a for a in client.get("/api/albums").json() if a["title"] == "Solo")
    tid = client.get(f"/api/albums/{song['id']}").json()["tracks"][0]["id"]
    client.put(f"/api/likes/{tid}")
    moved = tmp_path / "moved"
    shutil.copytree(extra, moved)
    shutil.rmtree(extra)
    r = client.post("/api/folders", json={"path": str(moved), "replace": str(extra)}).json()
    assert r["kept"] == 1
    scan()
    assert client.get("/api/likes/ids").json() == [tid]
    assert [f["path"] for f in client.get("/api/folders").json()["folders"]][1] == str(moved.resolve())

    # Saved: a restarted server keeps the list.
    from shelf import folders
    assert [str(p) for p in folders.load_saved(client.app.state.cfg.db_path)][1] == str(moved.resolve())

    # Removing it takes its songs out of the library.
    assert client.delete("/api/folders", params={"path": str(moved.resolve())}).status_code == 200
    scan()
    assert [f["tracks"] for f in client.get("/api/folders").json()["folders"]] == [4]
    assert client.get("/api/likes/ids").json() == []


def test_browse_lists_folders_only(client, tmp_path):
    login(client)
    (tmp_path / "a").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "file.txt").write_text("x")
    r = client.get("/api/folders/browse", params={"path": str(tmp_path)}).json()
    names = [d["name"] for d in r["dirs"]]
    assert "a" in names and ".hidden" not in names and "file.txt" not in names
    assert r["parent"] == str(tmp_path.parent)


def test_folders_locked_by_environment(client, tmp_path, monkeypatch):
    login(client)
    monkeypatch.setenv("SHELF_MUSIC_DIRS", str(tmp_path))
    assert client.get("/api/folders").json()["locked"] is True
    assert client.post("/api/folders", json={"path": str(tmp_path)}).status_code == 409


def test_upload_files_songs_by_their_tags(client, tmp_path, library):
    import io, zipfile
    login(client)
    song = (library / "Band" / "2001 - First" / "01 Opening.mp3").read_bytes()
    r = client.post("/api/upload?name=Opening.mp3&group=g1", content=song).json()
    assert r["status"] == "duplicate" or r["status"] == "added"
    other = (library / "band" / "Second" / "CD2" / "01 Late.flac").read_bytes()
    r = client.post("/api/upload?name=Late%20(copy).flac&group=g2", content=other).json()
    assert r == {"status": "added", "artist": "band", "album": "Second", "path": str(library / "band" / "Second" / "Late (copy).flac")}
    assert client.post("/api/upload?name=Late%20(copy).flac&group=g2", content=other).json()["status"] == "duplicate"
    # the album's cover, sent after its songs, lands next to them
    assert client.post("/api/upload?name=cover.jpg&group=g2", content=b"\xff\xd8fakejpeg").json()["status"] == "added"
    assert (library / "band" / "Second" / "cover.jpg").exists()
    # a ZIP
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Album/01 a.mp3", song)
        z.writestr("Album/folder.png", b"png")
        z.writestr("../../evil.mp3", song)
    r = client.post("/api/upload?name=album.zip&group=g3", content=buf.getvalue()).json()
    assert r["albums"] == ["Band – First"]
    assert not (tmp_path / "evil.mp3").exists()
    assert client.post("/api/upload?name=notes.exe", content=b"x").status_code == 400
