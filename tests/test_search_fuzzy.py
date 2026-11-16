"""Search forgives spelling mistakes and knows bands by their nicknames (fuzzy.py)."""

import json
import time

import pytest

from conftest import make_track
from shelf import fuzzy
from shelf.db import session, set_meta


def login(c):
    assert c.post("/api/login", json={"password": "hunter2"}).status_code == 200


@pytest.fixture
def bands(client, library):
    for artist, album, title in [("My Chemical Romance", "The Black Parade", "Welcome to the Black Parade"),
                                 ("Avenged Sevenfold", "City of Evil", "Bat Country"),
                                 ("AC/DC", "Back in Black", "Hells Bells"),
                                 ("Band", "Third", "MCR Anthem")]:
        make_track(library / artist.replace("/", "") / album / f"01 {title}.mp3", title=title, artist=artist, album=album, track=1)
    client.app.state.scanner.run_once()
    login(client)
    return client


def search(c, q):
    return c.get("/api/search", params={"q": q}).json()


def test_distance():
    assert fuzzy.distance("sevenfold", "sevenfold", 2) == 0
    assert fuzzy.distance("sevenfodl", "sevenfold", 2) == 1  # a swapped pair is one mistake
    assert fuzzy.distance("sevnfould", "sevenfold", 2) == 2
    assert fuzzy.distance("abcdef", "uvwxyz", 2) == 3  # gives up past the limit


def test_nicknames():
    assert fuzzy.nicknames("My Chemical Romance") == {"mcr", "mychemicalromance"}
    assert fuzzy.nicknames("AC/DC") == {"acdc"}
    assert fuzzy.nicknames("The Red Hot Chili Peppers") == {"trhcp", "rhcp", "theredhotchilipeppers"}
    assert fuzzy.nicknames("Queen") == set()


def test_spelling_mistakes_still_find_it(bands):
    assert [t["title"] for t in search(bands, "Opneing")["tracks"]] == ["Opening"]
    assert [a["name"] for a in search(bands, "avenged sevenfould")["artists"]] == ["Avenged Sevenfold"]
    assert [t["title"] for t in search(bands, "bat contry")["tracks"]] == ["Bat Country"]
    # A word that's in the library isn't "corrected" into others; short ones aren't touched.
    assert [t["title"] for t in search(bands, "closer")["tracks"]] == ["Closer"]
    assert search(bands, "zzzzzzzz")["tracks"] == []


def test_initials_and_run_together(bands):
    r = search(bands, "MCR")
    assert [a["name"] for a in r["artists"]] == ["My Chemical Romance"]
    # The song with "MCR" in its name comes first, then the band's.
    assert [t["title"] for t in r["tracks"]] == ["MCR Anthem", "Welcome to the Black Parade"]
    assert [a["title"] for a in r["albums"]] == ["The Black Parade"]
    assert [t["title"] for t in search(bands, "acdc")["tracks"]] == ["Hells Bells"]
    assert [t["title"] for t in search(bands, "mcr parade")["tracks"]] == ["Welcome to the Black Parade"]


def test_musicbrainz_names(bands):
    assert search(bands, "a7x")["artists"] == []
    db = bands.app.state.cfg.db_path
    with session(db) as conn:  # what the daily MusicBrainz check stores (releases.py)
        set_meta(conn, "mb_artist_genres", json.dumps({"avenged sevenfold": {"genres": [], "aliases": ["A7X"], "at": 1}}))
        set_meta(conn, "releases_checked", "1")
        fuzzy.index(conn, wait=True)  # searches meanwhile use the index from before
    r = search(bands, "A7X")
    assert [a["name"] for a in r["artists"]] == ["Avenged Sevenfold"]
    assert [t["title"] for t in r["tracks"]] == ["Bat Country"]


def test_subsonic_search_too(bands):
    base = {"u": "admin", "p": "hunter2", "v": "1.16.1", "c": "test", "f": "json"}
    def s3(q):
        return bands.get("/rest/search3", params={**base, "query": q}).json()["subsonic-response"]["searchResult3"]
    r = s3("mcr")
    assert [a["name"] for a in r["artist"]] == ["My Chemical Romance"]
    assert [s["title"] for s in r["song"]] == ["MCR Anthem", "Welcome to the Black Parade"]
    assert [s["title"] for s in s3("Opneing")["song"]] == ["Opening"]


def test_rebuilt_in_the_background(bands, library):
    db = bands.app.state.cfg.db_path
    with session(db) as conn:
        before = fuzzy.index(conn)
    make_track(library / "Muse" / "Absolution" / "01 Hysteria.mp3", title="Hysteria", artist="Muse", album="Absolution", track=1)
    bands.app.state.scanner.run_once()
    with session(db) as conn:
        assert fuzzy.index(conn) is before  # straight away: the old one, while the new one's built
    for _ in range(100):
        with session(db) as conn:
            if fuzzy.index(conn) is not before:
                break
        time.sleep(0.05)
    assert [t["title"] for t in search(bands, "hystria")["tracks"]] == ["Hysteria"]
