"""The rest of the Subsonic API and the OpenSubsonic extensions: what Navidrome's apps expect."""

import io
import json
from email.message import Message

from fastapi.testclient import TestClient

from shelf import podcasts
from shelf.db import session

from test_podcasts import RSS
from test_subsonic import Sub, login, setup


def first_song(sub):
    album = sub.ok("getAlbumList2", type="alphabeticalByName")["albumList2"]["album"][0]
    return sub.ok("getAlbum", id=album["id"])["album"]["song"][0]


def test_extensions_and_fuller_details(client):
    sub = setup(client)
    names = {e["name"] for e in sub.ok("getOpenSubsonicExtensions")["openSubsonicExtensions"]}
    assert {"apiKeyAuthentication", "indexBasedQueue", "playbackReport", "sonicSimilarity", "transcodeOffset",
            "transcoding", "getPodcastEpisode", "topSongsByArtistId", "songLyrics", "formPost"} <= names
    s = first_song(sub)
    # Fields an OpenSubsonic server supports are always there, empty when there's nothing to say.
    for k in ("genres", "artists", "albumArtists", "displayArtist", "displayAlbumArtist", "contributors",
              "displayComposer", "moods", "explicitStatus", "musicBrainzId", "isrc", "sortName", "comment", "bpm"):
        assert k in s, k
    assert s["artists"][0]["name"] == "Band" and s["channelCount"] == 1
    album = sub.ok("getAlbum", id=s["albumId"])["album"]
    for k in ("artists", "displayArtist", "genres", "releaseTypes", "recordLabels", "isCompilation", "musicBrainzId"):
        assert k in album, k
    artist = sub.ok("getArtists")["artists"]["index"][0]["artist"][0]
    top = sub.ok("getTopSongs", id=artist["id"], count=2)["topSongs"]["song"]
    assert len(top) == 2 and all(t["artist"].lower() == "band" for t in top)
    info = sub.ok("getArtistInfo2", id=artist["id"])["artistInfo2"]
    assert "similarArtist" in info or info.get("biography") == ""
    assert sub.ok("getAlbumInfo2", id=s["albumId"])["albumInfo"]["notes"] == ""


def test_api_keys(client):
    login(client)
    made = client.post("/api/me/apikeys", json={"name": "Symfonium"}).json()
    key = made["key"]
    assert key.startswith("shelf_") and made["keys"][0]["name"] == "Symfonium" and made["keys"][0]["hint"] == key[-4:]
    c = TestClient(client.app)

    def call(method, **params):
        return c.get(f"/rest/{method}", params={"f": "json", "v": "1.16.1", "c": "t", **params}).json()["subsonic-response"]

    assert call("tokenInfo", apiKey=key)["tokenInfo"]["username"] == "admin"
    assert call("ping", apiKey=key)["status"] == "ok"
    assert call("ping", apiKey="shelf_nope")["error"]["code"] == 44
    assert call("ping", apiKey=key, u="admin")["error"]["code"] == 43  # one way of signing in at a time
    listed = client.get("/api/me/apikeys").json()["keys"]
    assert listed[0]["usedAt"] and "key" not in listed[0]  # only ever shown once
    client.delete(f"/api/me/apikeys/{listed[0]['id']}")
    assert call("ping", apiKey=key)["error"]["code"] == 44


def test_accounts(client):
    sub = setup(client)
    sub.ok("createUser", username="sam", password="enc:" + "longpassword1".encode().hex(), email="", adminRole="false")
    assert {u["username"] for u in sub.ok("getUsers")["users"]["user"]} == {"admin", "sam"}
    sub.ok("updateUser", username="sam", adminRole="true")
    assert sub.ok("getUser", username="sam")["user"]["adminRole"] is True
    sub.ok("changePassword", username="sam", password="anotherpass2")
    c = TestClient(client.app)
    r = c.get("/rest/ping", params={"u": "sam", "p": "anotherpass2", "f": "json"}).json()["subsonic-response"]
    assert r["status"] == "ok"
    assert sub("deleteUser", username="admin")["error"]["code"] == 0  # not yourself
    sub.ok("deleteUser", username="sam")
    assert sub("getUser", username="sam")["error"]["code"] == 70
    av = sub.raw("getAvatar", username="admin")
    assert av.status_code == 200 and av.headers["content-type"] == "image/png" and av.content[:4] == b"\x89PNG"


def test_shares(client):
    sub = setup(client)
    s = first_song(sub)
    assert sub("createShare", id=s["id"])["error"]["code"] == 50  # off until an admin turns them on
    client.patch("/api/admin/shares", json={"enabled": True})
    share = sub.ok("createShare", id=s["albumId"], description="Listen", expires=4102444800000)["shares"]["share"][0]
    assert share["url"].endswith("/s/" + share["id"]) and share["description"] == "Listen"
    assert len(share["entry"]) == 2 and share["expires"].startswith("2100")
    sub.ok("updateShare", id=share["id"], description="Have a listen")
    assert sub.ok("getShares")["shares"]["share"][0]["description"] == "Have a listen"
    assert client.get(f"/s/{share['id']}").status_code == 200
    sub.ok("deleteShare", id=share["id"])
    assert sub.ok("getShares")["shares"].get("share", []) == []


def test_radio_and_chat(client):
    sub = setup(client)
    sub.ok("createInternetRadioStation", name="KEXP", streamUrl="https://kexp.example/stream", homepageUrl="https://kexp.org")
    st = sub.ok("getInternetRadioStations")["internetRadioStations"]["internetRadioStation"]
    assert st[0]["name"] == "KEXP" and st[0]["streamUrl"] == "https://kexp.example/stream"
    assert sub("createInternetRadioStation", name="x", streamUrl="ftp://nope")["error"]["code"] == 0
    sub.ok("updateInternetRadioStation", id=st[0]["id"], name="KEXP 90.3", streamUrl="https://kexp.example/stream")
    assert sub.ok("getInternetRadioStations")["internetRadioStations"]["internetRadioStation"][0]["name"] == "KEXP 90.3"
    sub.ok("deleteInternetRadioStation", id=st[0]["id"])
    assert sub.ok("getInternetRadioStations")["internetRadioStations"].get("internetRadioStation", []) == []

    sub.ok("addChatMessage", message="hello")
    msgs = sub.ok("getChatMessages")["chatMessages"]["chatMessage"]
    assert msgs[0]["message"] == "hello" and msgs[0]["username"] == "admin"
    assert sub.ok("getChatMessages", since=msgs[0]["time"])["chatMessages"].get("chatMessage", []) == []


def test_search_one(client):
    sub = setup(client)
    r = sub.ok("search", title="clos")["searchResult"]
    assert r["totalHits"] == 1 and r["match"][0]["title"] == "Closer"
    assert sub.ok("search", any="band", count=2)["searchResult"]["totalHits"] == 4


def test_queue_by_index(client):
    sub = setup(client)
    s = first_song(sub)
    sub.ok("savePlayQueueByIndex", id=[s["id"], s["id"]], currentIndex=1, position=5000)
    q = sub.ok("getPlayQueueByIndex")["playQueueByIndex"]
    assert q["currentIndex"] == 1 and q["position"] == 5000 and len(q["entry"]) == 2
    assert sub("savePlayQueueByIndex", id=s["id"], currentIndex=3)["error"]["code"] == 10
    assert sub.ok("getPlayQueue")["playQueue"]["current"] == s["id"]  # the same queue, either way
    sub.ok("savePlayQueueByIndex")  # nothing: clears it
    assert "entry" not in sub.ok("getPlayQueueByIndex")["playQueueByIndex"]


def test_playback_reports_count_a_play_once(client, monkeypatch):
    sub = setup(client)
    s = first_song(sub)  # two seconds long
    import shelf.subsonic_more as more
    clock = [1000.0]
    monkeypatch.setattr(more.time, "time", lambda: clock[0])
    sub.ok("reportPlayback", mediaId=s["id"], mediaType="song", positionMs=0, state="starting")
    sub.ok("reportPlayback", mediaId=s["id"], mediaType="song", positionMs=0, state="playing")
    np = sub.ok("getNowPlaying")["nowPlaying"]["entry"][0]
    assert np["state"] == "playing" and np["id"] == s["id"]
    clock[0] += 1.5
    sub.ok("reportPlayback", mediaId=s["id"], mediaType="song", positionMs=1500, state="paused")
    clock[0] += 5
    sub.ok("reportPlayback", mediaId=s["id"], mediaType="song", positionMs=1500, state="playing")
    sub.ok("reportPlayback", mediaId=s["id"], mediaType="song", positionMs=1500, state="stopped")
    assert sub.ok("getSong", id=s["id"])["song"]["playCount"] == 1
    assert sub.ok("getNowPlaying")["nowPlaying"].get("entry", []) == []
    assert sub("reportPlayback", mediaId=s["id"], mediaType="song", positionMs=0, state="dancing")["status"] == "failed"


def test_sounds_alike(client):
    sub = setup(client)
    with session(client.app.state.cfg.db_path) as conn:
        ids = [r[0] for r in conn.execute("SELECT id FROM tracks ORDER BY id")]
        # Fake fingerprints (sound.py needs ten songs, so copy the four a few times over).
        for n in range(3):
            for i, tid in enumerate(ids):
                if n:
                    conn.execute("""INSERT INTO tracks(path, mtime, size, title, artist, album, album_key, duration, added_at)
                                    SELECT path || ?, mtime, size, title || ?, artist, album, album_key, duration, added_at
                                    FROM tracks WHERE id = ?""", (f".{n}", f" {n}", tid))
        rows = conn.execute("SELECT id FROM tracks ORDER BY id").fetchall()
        for k, r in enumerate(rows):
            vec = [float((k * 7 + j) % 5) + (k % 4) * 3 for j in range(8)]
            conn.execute("UPDATE tracks SET sound = ? WHERE id = ?", (json.dumps(vec), r[0]))
    got = sub.ok("getSonicSimilarTracks", id=str(ids[0]), count=3)["sonicMatch"]
    assert len(got) == 3 and all(0 <= m["similarity"] <= 1 for m in got) and got[0]["similarity"] >= got[-1]["similarity"]
    path = sub.ok("findSonicPath", startSongId=str(ids[0]), endSongId=str(ids[2]), count=5)["sonicMatch"]
    assert path[0]["entry"]["id"] == str(ids[0]) and path[-1]["entry"]["id"] == str(ids[2]) and len(path) == 5
    assert len({m["entry"]["id"] for m in path}) == 5
    assert len(sub.ok("getSimilarSongs2", id=str(ids[0]), count=4)["similarSongs2"]["song"]) == 4


def test_formats_and_seeking(client):
    sub = setup(client)
    s = first_song(sub)
    mp3 = sub.raw("stream", id=s["id"], format="opus")
    assert mp3.status_code == 200 and mp3.headers["content-type"] == "audio/ogg" and mp3.content[:4] == b"OggS"
    later = sub.raw("stream", id=s["id"], format="mp3", maxBitRate=128, timeOffset=1)
    assert later.headers["content-type"] == "audio/mpeg" and 0 < len(later.content) < len(sub.raw("download", id=s["id"]).content)
    assert sub.raw("stream", id=s["id"], format="mp3").content == sub.raw("download", id=s["id"]).content  # already mp3

    c = sub.c
    info = {"name": "test", "platform": "test", "directPlayProfiles": [{"containers": ["flac"], "audioCodecs": ["flac"], "protocols": ["http"]}],
            "transcodingProfiles": [{"container": "mp3", "audioCodec": "mp3", "protocol": "http"}],
            "codecProfiles": [{"type": "AudioCodec", "name": "mp3", "limitations": [
                {"name": "audioBitrate", "comparison": "LessThanEqual", "values": ["160000"], "required": True}]}]}
    r = c.post("/rest/getTranscodeDecision", params={**sub.auth(), "mediaId": s["id"], "mediaType": "song"}, json=info)
    d = r.json()["subsonic-response"]["transcodeDecision"]
    assert d["canDirectPlay"] is False and d["canTranscode"] is True and d["transcodeStream"]["codec"] == "mp3"
    assert d["transcodeStream"]["audioBitrate"] == 160000 and d["sourceStream"]["codec"] == "mp3"
    got = sub.raw("getTranscodeStream", mediaId=s["id"], mediaType="song", transcodeParams=d["transcodeParams"], offset=1)
    assert got.status_code == 200 and got.headers["content-type"] == "audio/mpeg" and got.content
    info["directPlayProfiles"].append({"containers": ["mp3"], "audioCodecs": [], "protocols": []})
    d = c.post("/rest/getTranscodeDecision", params={**sub.auth(), "mediaId": s["id"], "mediaType": "song"},
               json=info).json()["subsonic-response"]["transcodeDecision"]
    assert d["canDirectPlay"] is True
    assert sub("getTranscodeDecision", mediaId=s["id"], mediaType="song")["error"]["code"] == 10  # no abilities sent


def test_podcasts(client, monkeypatch):
    monkeypatch.setattr(podcasts, "_read", lambda url, limit, headers=None, timeout=20: (RSS, None))
    sub = setup(client)
    sub.ok("createPodcastChannel", url="https://feed.podbean.com/someshow/feed.xml")
    ch = sub.ok("getPodcasts")["podcasts"]["channel"][0]
    assert ch["title"] == "Some Show" and ch["id"].startswith("pc-") and len(ch["episode"]) == 2
    ep = ch["episode"][1]
    assert ep["status"] == "completed" and ep["title"] == "Episode 1: Hello" and ep["streamId"]
    assert sub.ok("getPodcastEpisode", id=ep["id"])["podcastEpisode"]["title"] == "Episode 1: Hello"
    assert len(sub.ok("getNewestPodcasts", count=1)["newestPodcasts"]["episode"]) == 1
    assert sub.ok("getPodcasts", includeEpisodes="false")["podcasts"]["channel"][0].get("episode") is None

    sub.ok("downloadPodcastEpisode", id=ep["id"])  # kept in Your Episodes
    assert [e["title"] for e in client.get("/api/podcasts/saved").json()["episodes"]] == ["Episode 1: Hello"]
    sub.ok("deletePodcastEpisode", id=ep["id"])
    assert client.get("/api/podcasts/saved").json()["episodes"] == []

    class Upstream(io.BytesIO):
        status = 200
        headers = Message()
    up = Upstream(b"ID3audio")
    up.headers["Content-Type"] = "audio/mpeg"
    monkeypatch.setattr(podcasts, "open_url", lambda url, headers=None, timeout=20: up)
    r = sub.raw("stream", id=ep["streamId"])
    assert r.status_code == 200 and r.content == b"ID3audio"

    sub.ok("reportPlayback", mediaId=ep["id"], mediaType="podcast", positionMs=120000, state="paused")
    assert sub.ok("getPodcastEpisode", id=ep["id"])["podcastEpisode"]["bookmarkPosition"] == 120000
    sub.ok("scrobble", id=ep["streamId"])  # finished: never counted as a play
    with session(client.app.state.cfg.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM plays").fetchone()[0] == 0
    sub.ok("deletePodcastChannel", id=ch["id"])
    assert sub.ok("getPodcasts")["podcasts"].get("channel", []) == []


def test_things_shelf_does_not_do_say_so(client):
    sub = setup(client)
    assert sub("jukeboxControl", action="status")["error"]["code"] == 50
    assert sub("getVideoInfo", id="1")["error"]["code"] == 70
    assert sub("noSuchThing")["error"]["code"] == 0


def test_music_folders(tmp_path, library):
    from conftest import make_track
    from shelf.app import create_app
    from shelf.config import Config

    other = tmp_path / "music2"  # its name starts like the first folder's: still a folder of its own
    make_track(other / "Choir" / "Hymns" / "01 Hymn.mp3", title="Hymn", artist="Choir", album="Hymns", track=1)
    cfg = Config(music_dirs=[library, other], data_dir=tmp_path / "d2", password="hunter2", online_lyrics=False,
                 music_videos=False, artist_info=False, analyze_tempo=False)
    app = create_app(cfg, start_scanner=False)
    app.state.scanner.run_once()
    with TestClient(app) as c:
        sub = setup(c)
        folders = sub.ok("getMusicFolders")["musicFolders"]["musicFolder"]
        assert [f["name"] for f in folders] == ["music", "music2"]
        names = lambda body: sorted(a["name"] for i in body["index"] for a in i["artist"])  # noqa: E731
        assert names(sub.ok("getArtists")["artists"]) == ["Band", "Choir"]
        assert names(sub.ok("getArtists", musicFolderId=2)["artists"]) == ["Choir"]
        assert names(sub.ok("getIndexes", musicFolderId=1)["indexes"]) == ["Band"]
        albums = sub.ok("getAlbumList2", type="alphabeticalByName", musicFolderId=2)["albumList2"]["album"]
        assert [a["name"] for a in albums] == ["Hymns"]
        assert {s["title"] for s in sub.ok("getRandomSongs", size=10, musicFolderId=2)["randomSongs"]["song"]} == {"Hymn"}
        found = sub.ok("search3", query="", songCount=50, musicFolderId=1)["searchResult3"]
        assert len(found["song"]) == 4 and all(a["name"] != "Hymns" for a in found["album"])
        assert sub("getAlbumList2", type="newest", musicFolderId=9)["error"]["code"] == 70
        assert sub.ok("getUser")["user"]["folder"] == [1, 2]
