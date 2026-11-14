"""Imported playlists keep the songs the library doesn't have, marked missing, and ask for their
albums in Requests. A scan that brings a song in puts it in its place."""

from fastapi.testclient import TestClient

from conftest import make_track
from shelf import missing
from shelf.db import session
from shelf.imports import want


def login(c, username="admin", password="hunter2"):
    assert c.post("/api/login", json={"username": username, "password": password}).status_code == 200


def imported(client, text):
    [pl] = client.post("/api/playlists/import", json={"text": text}).json()["playlists"]
    songs = [{"trackId": s["track"]["id"]} if s["track"] else s["song"] for s in pl["songs"]]
    return client.post("/api/playlists", json={"name": pl["name"] or "Imported", "songs": songs}).json()


CSV = """Track Name,Artist Name(s),Album Name
Opening,Band,First
Around the World,Daft Punk,Homework
Closer,Band,First
Da Funk,Daft Punk,Homework
One More Time,Daft Punk,Discovery
Lost Song,Band,First
"""


def test_missing_songs_stay_in_their_places(client):
    login(client)
    r = client.post("/api/playlists/import", json={"text": CSV, "filename": "trip.csv"})
    [pl] = r.json()["playlists"]
    assert pl["found"] == 2
    gone = [s for s in pl["songs"] if not s["track"]]
    assert gone[0]["song"] == {"artist": "Daft Punk", "title": "Around the World", "album": "Homework",
                               "duration": None, "text": "", "path": ""}
    made = client.post("/api/playlists", json={"name": "Trip", "songs": [
        {"trackId": s["track"]["id"]} if s["track"] else s["song"] for s in pl["songs"]]}).json()
    assert made["trackCount"] == 2 and made["missing"] == 4

    p = client.get(f"/api/playlists/{made['id']}").json()
    assert [t["title"] for t in p["tracks"]] == ["Opening", "Closer"]
    # Where each missing one sits: after how many of the real songs.
    assert [(m["title"], m["after"]) for m in p["missingSongs"]] == [
        ("Around the World", 1), ("Da Funk", 2), ("One More Time", 2), ("Lost Song", 2)]


def test_their_albums_are_requested_once_each(client):
    login(client)
    client.post("/api/requests", json={"artist": "Daft Punk", "album": "Discovery"})  # someone asked already
    pid = imported(client, CSV)["id"]

    asked = client.get("/api/requests").json()["requests"]
    # Homework is asked for once for two songs; Discovery was asked for already; Band's "First"
    # is on the shelf (one song of it just didn't match), so it isn't asked for.
    assert sorted((x["artist"], x["album"]) for x in asked) == [("Daft Punk", "Discovery"), ("Daft Punk", "Homework")]
    homework = next(x for x in asked if x["album"] == "Homework")
    assert homework["note"].startswith("For the playlist ‘")
    gaps = {m["title"]: m for m in client.get(f"/api/playlists/{pid}").json()["missingSongs"]}
    assert gaps["Around the World"]["requestId"] == gaps["Da Funk"]["requestId"] == homework["id"]
    assert gaps["One More Time"]["request"] == "open" and gaps["One More Time"]["requestId"]
    assert gaps["Lost Song"]["requestId"] is None


def test_without_an_album_the_artist_is_asked_for(client):
    login(client)
    pid = imported(client, "Artist,Title\nBand,Opening\nNobody,Nothing\nAlso Nobody,Something\nNobody,Else\n")["id"]
    asked = client.get("/api/requests").json()["requests"]
    assert sorted((x["artist"], x["album"]) for x in asked) == [("Also Nobody", None), ("Nobody", None)]
    p = client.get(f"/api/playlists/{pid}").json()
    assert [(m["artist"], m["title"], m["after"]) for m in p["missingSongs"]] == [
        ("Nobody", "Nothing", 1), ("Also Nobody", "Something", 1), ("Nobody", "Else", 1)]


def test_a_pasted_line_is_only_asked_for_once_musicbrainz_places_it(client):
    # "A - B" could be either way round, and with artist info off nothing can tell: no guessing.
    login(client)
    pid = imported(client, "Band - Opening\nNobody - Nothing")["id"]
    assert client.get("/api/requests").json()["requests"] == []
    [m] = client.get(f"/api/playlists/{pid}").json()["missingSongs"]
    assert (m["artist"], m["title"], m["requestId"]) == ("Nobody", "Nothing", None)


def test_a_scan_puts_the_song_in_its_place(client, library):
    login(client)
    pid = imported(client, CSV)["id"]
    make_track(library / "Daft Punk" / "Homework" / "01 Da Funk.mp3", title="Da Funk", artist="Daft Punk",
               album="Homework", track=1)
    client.app.state.scanner.run_once()  # the scan's follow-up fills it in
    p = client.get(f"/api/playlists/{pid}").json()
    assert [t["title"] for t in p["tracks"]] == ["Opening", "Closer", "Da Funk"]
    assert [(m["title"], m["after"]) for m in p["missingSongs"]] == [
        ("Around the World", 1), ("One More Time", 3), ("Lost Song", 3)]
    # And the request for Homework is done, since the album's on the shelf now.
    homework = next(x for x in client.get("/api/requests").json()["requests"] if x["album"] == "Homework")
    assert homework["status"] == "done"


def test_reordering_and_removing(client):
    login(client)
    pid = imported(client, CSV)["id"]
    p = client.get(f"/api/playlists/{pid}").json()
    a, b = (t["entryId"] for t in p["tracks"])
    assert client.put(f"/api/playlists/{pid}/order", json={"entryIds": [b, a]}).status_code == 200
    p = client.get(f"/api/playlists/{pid}").json()
    # "Around the World" came after Opening, and still does; the rest followed Closer.
    assert [t["title"] for t in p["tracks"]] == ["Closer", "Opening"]
    assert [(m["title"], m["after"]) for m in p["missingSongs"]] == [
        ("Da Funk", 1), ("One More Time", 1), ("Lost Song", 1), ("Around the World", 2)]

    gone = p["missingSongs"][0]["id"]
    assert client.delete(f"/api/playlists/{pid}/missing/{gone}").json()["missing"] == 3
    assert client.delete(f"/api/playlists/{pid}/missing/{gone}").status_code == 404
    # Songs added later go at the very end, after the missing ones.
    client.post(f"/api/playlists/{pid}/tracks", json={"trackIds": [p["tracks"][0]["id"]]})
    p = client.get(f"/api/playlists/{pid}").json()
    assert len(p["tracks"]) == 3 and max(m["after"] for m in p["missingSongs"]) == 2


def test_someone_else_cant_remove_them(client):
    login(client)
    pid = imported(client, CSV)["id"]
    mid = client.get(f"/api/playlists/{pid}").json()["missingSongs"][0]["id"]
    client.post("/api/users", json={"username": "sam", "password": "sam-pass"})
    sam = TestClient(client.app)
    login(sam, "sam", "sam-pass")
    assert sam.delete(f"/api/playlists/{pid}/missing/{mid}").status_code == 404


def test_old_apps_still_make_playlists_from_track_ids(client):
    login(client)
    ids = [t["id"] for t in client.get("/api/search", params={"q": "Opening"}).json()["tracks"]]
    made = client.post("/api/playlists", json={"name": "Plain", "trackIds": ids}).json()
    assert made["trackCount"] == 1 and made["missing"] == 0
    assert client.get(f"/api/playlists/{made['id']}").json()["missingSongs"] == []


# ---------- what MusicBrainz says the album is ----------

def rel(title, gid, kind="Album", extra=(), date="2001-01-01", status="Official"):
    return {"status": status, "date": date,
            "release-group": {"id": gid, "title": title, "primary-type": kind, "secondary-types": list(extra)}}


def fake_mb(calls):
    def mb(path, retries=4, **params):
        calls.append(params["query"])
        assert path == "recording"
        return {"recordings": [
            {"title": "Da Funk (radio edit)", "score": 100,
             "artist-credit": [{"name": "Daft Punk", "artist": {"id": "dp"}}],
             "releases": [rel("Musique Vol. 1", "comp", extra=["Compilation"], date="2006"),
                          rel("Da Funk", "single", kind="Single", date="1995-11-01"),
                          rel("Homework", "homework", date="1997-01-20"),
                          rel("Homework", "boot", date="1996", status="Bootleg")]},
            {"title": "Da Funk", "score": 95, "artist-credit": [{"name": "Somebody Else"}],
             "releases": [rel("Covers", "covers", date="1990")]},
            {"title": "Something Else", "score": 99, "artist-credit": [{"name": "Daft Punk"}],
             "releases": [rel("Elsewhere", "else", date="1980")]}]}
    return mb


def test_the_album_a_song_belongs_on():
    calls = []
    got = missing.album_of("Daft Punk", "Da Funk", mb=fake_mb(calls))
    # The studio album, not the single, the compilation, the bootleg or someone else's cover.
    assert got == {"artist": "Daft Punk", "artistId": "dp", "album": "Homework", "albumId": "homework",
                   "year": 1997, "kind": "Album"}
    assert "artist:(Daft Punk)" in calls[0]
    assert missing.album_of("Somebody", "Something Else", mb=fake_mb(calls)) is None


def test_either_way_round():
    calls = []
    assert missing.candidates(want(text="Da Funk - Daft Punk")) == [("Da Funk", "Daft Punk"), ("Daft Punk", "Da Funk")]
    assert missing.candidates(want(artist="Daft Punk", title="Da Funk")) == [("Daft Punk", "Da Funk")]
    assert missing.candidates(want(text="a cat playing piano")) == []
    assert missing.album_of("Da Funk", "Daft Punk", mb=fake_mb(calls)) is None


def test_guessing_artist_and_title():
    assert missing.guess(want(text="Daft Punk - Da Funk (Official Video)", artist="DaftPunkVEVO")) == ("Daft Punk", "Da Funk")
    assert missing.guess(want(text="Da Funk", artist="Daft Punk")) == ("Daft Punk", "Da Funk")
    assert missing.guess(want(path="C:\\Music\\03 - Daft Punk - Da Funk.mp3")) == ("Daft Punk", "Da Funk")
    assert missing.plan(want(text="Some video"), lookup=False) == ""
    assert missing.plan(want(text="Some video"), lookup=True) == ""  # no artist anywhere
    assert missing.plan(want(text="Queen - Some video"), lookup=True) == "lookup"
    assert missing.plan(want(artist="A", title="B"), lookup=False) == "artist"
    assert missing.plan(want(artist="A", title="B", album="C"), lookup=True) == "album"


def test_looked_up_in_the_background(client, monkeypatch):
    login(client)
    pid = client.post("/api/playlists", json={"name": "Vids", "songs": [
        {"text": "Da Funk - Daft Punk", "artist": "DaftPunkVEVO"},
        {"text": "Daft Punk - Da Funk"},
        {"text": "a cat playing piano"}]}).json()["id"]
    assert client.get("/api/requests").json()["requests"] == []  # artist info is off in tests
    later = [(m["id"], want(text=t)) for m, t in zip(client.get(f"/api/playlists/{pid}").json()["missingSongs"],
                                                       ["Da Funk - Daft Punk", "", "a cat playing piano"])]
    later[1] = (later[1][0], want(artist="Daft Punk", title="Da Funk"))
    calls = []

    def mb(path, retries=4, **params):
        if "cat" in params["query"]:
            return {"recordings": []}
        return fake_mb(calls)(path, **params)
    uid = 1
    asked = missing.request_looked_up(lambda: session(client.app.state.cfg.db_path), uid, "Vids", later, mb=mb)
    assert asked == 1
    # "Da Funk" by "Daft Punk" the wrong way round first, then the right way; the second song is
    # the same one, so it isn't looked up again.
    assert len(calls) == 2
    [r] = client.get("/api/requests").json()["requests"]
    assert (r["artist"], r["album"], r["albumId"], r["year"]) == ("Daft Punk", "Homework", "homework", 1997)
    gaps = client.get(f"/api/playlists/{pid}").json()["missingSongs"]
    assert gaps[0]["requestId"] == gaps[1]["requestId"] == r["id"] and gaps[2]["requestId"] is None
