"""The Subsonic API: apps like Symfonium, Feishin, Substreamer and DSub play from Shelf."""

import hashlib
import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient

NS = "{http://subsonic.org/restapi}"


def login(c, username="admin", password="hunter2"):
    assert c.post("/api/login", json={"username": username, "password": password}).status_code == 200


def app_password(c):
    r = c.post("/api/me/subsonic").json()
    assert r["username"] == "admin" and len(r["password"]) >= 16
    return r["password"]


class Sub:
    """An app talking Subsonic: token auth (md5 of password + salt), JSON."""

    def __init__(self, client, password, username="admin"):
        self.c, self.u, self.pw = TestClient(client.app), username, password

    def auth(self):
        salt = "c19b2d"
        return {"u": self.u, "t": hashlib.md5((self.pw + salt).encode()).hexdigest(), "s": salt,
                "v": "1.16.1", "c": "test", "f": "json"}

    def raw(self, method, **params):
        return self.c.get(f"/rest/{method}.view", params={**self.auth(), **params})

    def __call__(self, method, **params):
        r = self.raw(method, **params)
        assert r.status_code == 200, r.text
        body = r.json()["subsonic-response"]
        return body

    def ok(self, method, **params):
        body = self(method, **params)
        assert body["status"] == "ok", body
        return body


def setup(client):
    login(client)
    return Sub(client, app_password(client))


def test_signing_in(client):
    sub = setup(client)
    body = sub.ok("ping")
    assert body["version"] and body["openSubsonic"] is True and body["type"] == "shelf"

    bad = Sub(client, "wrong-password")
    assert bad("ping")["error"]["code"] == 40
    # Plain and hex-encoded passwords work too, and so does the account's own password.
    c = TestClient(client.app)
    for p in (sub.pw, "enc:" + sub.pw.encode().hex(), "hunter2"):
        r = c.get("/rest/ping", params={"u": "admin", "p": p, "v": "1.13.0", "c": "old", "f": "json"})
        assert r.json()["subsonic-response"]["status"] == "ok", p
    # Missing credentials: code 10. Token auth can't use the account password (it's never stored).
    assert c.get("/rest/ping", params={"f": "json"}).json()["subsonic-response"]["error"]["code"] == 10
    acct = Sub(client, "hunter2")
    assert acct("ping")["error"]["code"] == 40

    # A new app password replaces the old one; removing it stops token sign-in.
    sub2 = Sub(client, app_password(client))
    assert sub("ping")["status"] == "failed" and sub2("ping")["status"] == "ok"
    client.delete("/api/me/subsonic")
    assert sub2("ping")["status"] == "failed"


def test_xml_is_the_default(client):
    sub = setup(client)
    params = {k: v for k, v in sub.auth().items() if k != "f"}
    r = sub.c.get("/rest/getArtists", params=params)
    assert r.headers["content-type"].startswith("text/xml")
    root = ET.fromstring(r.content)
    assert root.tag == NS + "subsonic-response" and root.get("status") == "ok"
    names = [a.get("name") for a in root.iter(NS + "artist")]
    assert names == ["Band"]
    r = sub.c.get("/rest/ping", params={**params, "u": "nobody"})
    err = ET.fromstring(r.content).find(NS + "error")
    assert err.get("code") == "40"


def test_browsing_artists_albums_and_songs(client):
    sub = setup(client)
    index = sub.ok("getArtists")["artists"]["index"]
    artist = index[0]["artist"][0]
    assert index[0]["name"] == "B" and artist["name"] == "Band" and artist["albumCount"] == 2

    albums = sub.ok("getArtist", id=artist["id"])["artist"]["album"]
    assert sorted(a["name"] for a in albums) == ["First", "Second"]
    first = next(a for a in albums if a["name"] == "First")
    assert first["songCount"] == 2 and first["coverArt"] and first["artistId"] == artist["id"]

    album = sub.ok("getAlbum", id=first["id"])["album"]
    songs = album["song"]
    assert [s["title"] for s in songs] == ["Opening", "Closer"]
    s = songs[0]
    assert s["track"] == 1 and s["albumId"] == first["id"] and s["suffix"] == "mp3"
    assert s["contentType"] == "audio/mpeg" and s["duration"] == 2 and s["isDir"] is False
    assert sub.ok("getSong", id=s["id"])["song"]["title"] == "Opening"

    # Folder-style browsing, for older apps.
    idx = sub.ok("getIndexes")["indexes"]["index"][0]["artist"][0]
    d = sub.ok("getMusicDirectory", id=idx["id"])["directory"]
    assert {c["title"] for c in d["child"]} == {"First", "Second"} and all(c["isDir"] for c in d["child"])
    d2 = sub.ok("getMusicDirectory", id=d["child"][0]["id"])["directory"]
    assert all(not c["isDir"] for c in d2["child"])

    assert sub("getAlbum", id="al-999999")["error"]["code"] == 70
    assert sub("getAlbum")["error"]["code"] == 10
    assert sub.ok("getMusicFolders")["musicFolders"]["musicFolder"][0]["id"] == 1


def test_whole_library_sync_through_empty_search(client):
    sub = setup(client)
    r = sub.ok("search3", query="", songCount=3, songOffset=0, albumCount=10, artistCount=10)["searchResult3"]
    assert len(r["song"]) == 3 and len(r["album"]) == 2 and len(r["artist"]) == 1
    more = sub.ok("search3", query='""', songCount=3, songOffset=3)["searchResult3"]
    assert len(more["song"]) == 1
    found = sub.ok("search3", query="clos")["searchResult3"]
    assert [s["title"] for s in found["song"]] == ["Closer"]
    assert sub.ok("search3", query="%")["searchResult3"].get("song", []) == []  # a % is a %, not "anything"
    assert sub.ok("search2", query="early")["searchResult2"]["song"][0]["title"] == "Early"


def test_streaming_downloads_and_covers(client):
    sub = setup(client)
    album = sub.ok("getAlbumList2", type="alphabeticalByName")["albumList2"]["album"][0]
    song = sub.ok("getAlbum", id=album["id"])["album"]["song"][0]
    r = sub.raw("stream", id=song["id"])
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg" and len(r.content) > 1000
    assert sub.raw("download", id=song["id"]).content == r.content
    cover = sub.raw("getCoverArt", id=album["coverArt"], size=100)
    assert cover.status_code == 200 and cover.headers["content-type"].startswith("image/")
    assert sub.raw("stream", id="999999").json()["subsonic-response"]["error"]["code"] == 70


def test_lists_genres_and_random(client):
    sub = setup(client)
    for kind in ("newest", "random", "alphabeticalByName", "alphabeticalByArtist", "recent", "frequent", "highest", "starred"):
        assert sub.ok("getAlbumList2", type=kind)["albumList2"] is not None
    assert len(sub.ok("getAlbumList2", type="newest", size=1)["albumList2"]["album"]) == 1
    assert len(sub.ok("getAlbumList2", type="byYear", fromYear=2000, toYear=2002)["albumList2"]["album"]) == 2
    assert sub.ok("getAlbumList2", type="byYear", fromYear=1990, toYear=1991)["albumList2"].get("album", []) == []
    assert len(sub.ok("getAlbumList", type="newest")["albumList"]["album"]) == 2
    assert len(sub.ok("getRandomSongs", size=3)["randomSongs"]["song"]) == 3
    assert "genres" in sub.ok("getGenres")


def test_stars_are_favourites(client):
    sub = setup(client)
    album = sub.ok("getAlbumList2", type="alphabeticalByName")["albumList2"]["album"][0]
    songs = sub.ok("getAlbum", id=album["id"])["album"]["song"]
    sub.ok("star", id=songs[0]["id"], albumId=album["id"])
    assert int(songs[0]["id"]) in client.get("/api/likes/ids").json()  # the same as liking it in Shelf
    starred = sub.ok("getStarred2")["starred2"]
    assert [s["id"] for s in starred["song"]] == [songs[0]["id"]]
    assert [a["id"] for a in starred["album"]] == [album["id"]]
    assert sub.ok("getSong", id=songs[0]["id"])["song"]["starred"]
    sub.ok("unstar", id=songs[0]["id"], albumId=album["id"])
    assert client.get("/api/likes/ids").json() == []
    assert sub.ok("getStarred")["starred"].get("song", []) == []


def test_playlists(client):
    sub = setup(client)
    songs = sub.ok("getRandomSongs", size=4)["randomSongs"]["song"]
    ids = [s["id"] for s in songs]
    made = sub.ok("createPlaylist", name="Road trip", songId=ids[:2])["playlist"]
    assert made["name"] == "Road trip" and made["songCount"] == 2 and made["owner"] == "admin"
    pid = made["id"]
    assert pid in [p["id"] for p in sub.ok("getPlaylists")["playlists"]["playlist"]]
    assert any(p["id"] == int(pid) for p in client.get("/api/playlists").json())  # it's a Shelf playlist

    sub.ok("updatePlaylist", playlistId=pid, name="Long road trip", songIdToAdd=ids[2:], songIndexToRemove=0)
    pl = sub.ok("getPlaylist", id=pid)["playlist"]
    assert pl["name"] == "Long road trip" and [e["id"] for e in pl["entry"]] == ids[1:]
    sub.ok("createPlaylist", playlistId=pid, songId=[ids[0]])  # replaces the songs
    assert [e["id"] for e in sub.ok("getPlaylist", id=pid)["playlist"]["entry"]] == [ids[0]]

    # Someone else can't change or delete it.
    client.post("/api/users", json={"username": "sam", "password": "sam-pass"})
    sam_client = TestClient(client.app)
    login(sam_client, "sam", "sam-pass")
    sam = Sub(client, sam_client.post("/api/me/subsonic").json()["password"], "sam")
    assert sam("deletePlaylist", id=pid)["error"]["code"] in (50, 70)
    assert sam("getPlaylist", id=pid)["error"]["code"] == 70  # private
    sub.ok("deletePlaylist", id=pid)
    assert sub("getPlaylist", id=pid)["error"]["code"] == 70


def test_scrobbles_count_as_plays(client):
    sub = setup(client)
    song = sub.ok("getRandomSongs", size=1)["randomSongs"]["song"][0]
    sub.ok("scrobble", id=song["id"], submission="false")  # now playing
    now = sub.ok("getNowPlaying")["nowPlaying"]["entry"]
    assert now[0]["id"] == song["id"] and now[0]["username"] == "admin"
    sub.ok("scrobble", id=song["id"], time=1_700_000_000_000)
    assert client.get("/api/tracks/recent").json()[0]["id"] == int(song["id"])
    assert sub.ok("getSong", id=song["id"])["song"]["playCount"] == 1


def test_user_scan_and_extensions(client):
    sub = setup(client)
    user = sub.ok("getUser", username="admin")["user"]
    assert user["adminRole"] is True and user["streamRole"] is True
    assert "scanStatus" in sub.ok("getScanStatus")
    exts = {e["name"] for e in sub.ok("getOpenSubsonicExtensions")["openSubsonicExtensions"]}
    assert {"formPost", "songLyrics"} <= exts
    song = sub.ok("getRandomSongs", size=1)["randomSongs"]["song"][0]
    assert sub.ok("getLyricsBySongId", id=song["id"])["lyricsList"].get("structuredLyrics", []) == []
    assert sub.ok("getLicense")["license"]["valid"] is True
    # Form posts (OpenSubsonic formPost) and CORS for web apps.
    r = sub.c.post("/rest/ping.view", data=sub.auth())
    assert r.json()["subsonic-response"]["status"] == "ok"
    assert sub.raw("ping").headers["access-control-allow-origin"] == "*"
