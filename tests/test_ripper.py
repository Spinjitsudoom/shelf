import stat
import time

from shelf import ripper

TOC = """Table of contents (audio tracks only):
track        length               begin        copy pre ch
===========================================================
  1.    15213 [03:22.63]        0 [00:00.00]    no   no  2
  2.    16951 [03:46.01]    15213 [03:22.63]    no   no  2
TOTAL   32164 [07:08.64]    (audio only)
"""


def fake_drive(tmp_path, monkeypatch):
    """A stand-in for cd-paranoia: -Q prints a two-track TOC, -w N file writes a short WAV."""
    script = tmp_path / "paranoia"
    script.write_text(f"""#!/bin/sh
if [ "$3" = "-Q" ]; then cat >&2 <<'TOC'
{TOC}
TOC
exit 0; fi
ffmpeg -v error -y -f lavfi -i sine=frequency=$((300 + $4 * 100)):duration=1 "$5"
""")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    dev = tmp_path / "sr0"
    dev.touch()
    monkeypatch.setattr(ripper, "PARANOIA", str(script))
    monkeypatch.setattr(ripper, "DEVICE", str(dev))
    monkeypatch.setattr(ripper, "lookup", lambda *a: {"artist": "Band", "album": "Live Disc", "year": "1999",
                                                       "tracks": [{"title": "Intro", "artist": "Band"}, {"title": "Encore/Outro", "artist": "Band"}],
                                                       "releaseId": None, "groupId": None})
    monkeypatch.setattr(ripper, "fetch_cover", lambda *a: None)
    monkeypatch.setattr(ripper.subprocess, "run", _no_eject(ripper.subprocess.run))


def _no_eject(run):
    def wrapped(cmd, *a, **k):
        if cmd and cmd[0] == "eject":
            return None
        return run(cmd, *a, **k)
    return wrapped


def wait(client, status):
    for _ in range(100):
        s = client.get("/api/cd").json()
        if s["status"] == status:
            return s
        time.sleep(0.1)
    raise AssertionError(s)


def test_toc_and_disc_id():
    tracks = ripper.parse_toc(TOC)
    assert [t["number"] for t in tracks] == [1, 2] and tracks[1]["start"] == 15213
    assert ripper.toc_offsets(tracks) == (1, 2, 32314, [150, 15363])
    assert ripper.disc_id(1, 6, 95462, [150, 15363, 32314, 46592, 63414, 80489]) == "49HHV7Eb8UKF3aQiNmu1GR8vKTY-"


def test_read_and_rip_a_disc(client, tmp_path, monkeypatch, library):
    fake_drive(tmp_path, monkeypatch)
    assert client.post("/api/login", json={"password": "hunter2"}).status_code == 200
    assert client.get("/api/cd").json()["available"] is True
    client.post("/api/cd/read")
    s = wait(client, "ready")
    assert s["disc"]["album"] == "Live Disc" and [t["seconds"] for t in s["disc"]["tracks"]] == [203, 226]
    assert client.post("/api/cd/rip", json={"artist": "Band", "album": "", "titles": []}).status_code == 400
    client.post("/api/cd/rip", json={"artist": "Band", "album": "Live Disc", "year": "1999", "titles": ["Intro", "Encore/Outro"]})
    s = wait(client, "done")
    folder = library / "Band" / "Live Disc"
    assert sorted(p.name for p in folder.iterdir()) == ["01 Intro.flac", "02 Encore Outro.flac"]
    from shelf.tags import read_tags
    tags = read_tags(folder / "02 Encore Outro.flac")
    assert (tags.title, tags.album, tags.track_no, tags.year) == ("Encore/Outro", "Live Disc", 2, 1999)
