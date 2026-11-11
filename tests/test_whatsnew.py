"""The "What's new" notes the apps show after an update: one entry per release, newest first."""

import json
from pathlib import Path

from shelf import __version__

NOTES = Path(__file__).parent.parent / "src" / "shelf" / "web" / "whatsnew.json"


def version(v):
    return tuple(int(x) for x in v.split("."))


def test_every_release_has_notes_newest_first():
    notes = json.loads(NOTES.read_text(encoding="utf-8"))
    assert notes[0]["version"] == __version__, "Write this version's notes at the top of whatsnew.json"
    versions = [version(n["version"]) for n in notes]
    assert versions == sorted(versions, reverse=True) and len(set(versions)) == len(versions)
    for n in notes:
        assert n.get("new") or n.get("fixed"), n["version"]
        for item in n.get("new", []):
            assert item["title"].strip() and item["text"].strip()
            assert set(item) <= {"title", "text", "admin"}
        assert all(isinstance(f, str) and f.strip() for f in n.get("fixed", []))


def test_the_notes_are_served(client):
    r = client.get("/whatsnew.json")
    assert r.status_code == 200 and r.json()[0]["version"] == __version__
