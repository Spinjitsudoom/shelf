from shelf import videos


def login(client):
    assert client.post("/api/login", json={"password": "hunter2"}).status_code == 200


def all_tracks(client):
    out = []
    for a in client.get("/api/albums").json():
        out += client.get(f"/api/albums/{a['id']}").json()["tracks"]
    return {t["title"]: t for t in out}


# ---------- playlists ----------

def test_playlist_lifecycle(client):
    login(client)
    t = all_tracks(client)
    p = client.post("/api/playlists", json={}).json()
    assert p["name"] == "My Playlist #1" and p["trackCount"] == 0

    r = client.post(f"/api/playlists/{p['id']}/tracks", json={"trackIds": [t["Opening"]["id"], t["Late"]["id"], 99999]}).json()
    assert r["added"] == 2 and r["trackCount"] == 2  # unknown ids are skipped
    client.post(f"/api/playlists/{p['id']}/tracks", json={"trackIds": [t["Opening"]["id"]]})  # duplicates are allowed

    detail = client.get(f"/api/playlists/{p['id']}").json()
    assert [x["title"] for x in detail["tracks"]] == ["Opening", "Late", "Opening"]
    assert len(detail["covers"]) == 1  # only "First" has art

    # reorder: reverse
    ids = [x["entryId"] for x in detail["tracks"]]
    assert client.put(f"/api/playlists/{p['id']}/order", json={"entryIds": ids[::-1]}).status_code == 200
    assert client.put(f"/api/playlists/{p['id']}/order", json={"entryIds": ids[:2]}).status_code == 409
    detail = client.get(f"/api/playlists/{p['id']}").json()
    assert [x["title"] for x in detail["tracks"]] == ["Opening", "Late", "Opening"][::-1]

    # remove one entry, rename, list
    client.delete(f"/api/playlists/{p['id']}/tracks/{ids[1]}")
    client.patch(f"/api/playlists/{p['id']}", json={"name": "  Drive  ", "description": "for the car"})
    lst = client.get("/api/playlists").json()
    assert lst[0]["name"] == "Drive" and lst[0]["description"] == "for the car" and lst[0]["trackCount"] == 2

    assert client.delete(f"/api/playlists/{p['id']}").status_code == 200
    assert client.get(f"/api/playlists/{p['id']}").status_code == 404


def test_playlist_entries_go_with_deleted_files(client, library):
    login(client)
    t = all_tracks(client)
    p = client.post("/api/playlists", json={"name": "Mix", "trackIds": [t["Closer"]["id"], t["Early"]["id"]]}).json()
    assert p["trackCount"] == 2
    (library / "Band" / "2001 - First" / "02 Closer.mp3").unlink()
    client.app.state.scanner.run_once()
    detail = client.get(f"/api/playlists/{p['id']}").json()
    assert [x["title"] for x in detail["tracks"]] == ["Early"]


# ---------- music videos ----------

RESULTS = [
    {"id": "lyric1", "title": "YUNGBLUD - Parents (Lyrics / Lyric Video)", "channel": "Armair Beats", "duration": 172, "view_count": 8_212_735},
    {"id": "live1", "title": "YUNGBLUD - Parents (Live) | Vevo LIFT Live Sessions", "channel": "YUNGBLUD", "duration": 206, "view_count": 1_681_866},
    {"id": "official", "title": "YUNGBLUD - Parents", "channel": "YUNGBLUD", "duration": 175, "view_count": 142_731_470},
    {"id": "art", "title": "parents", "channel": "YUNGBLUD - Topic", "duration": 172, "view_count": 864_589},
    {"id": "fan", "title": "𝕡𝕒𝕣𝕖𝕟𝕥𝕤", "channel": "kinnafiles", "duration": 165, "view_count": 29_206},
]


def test_video_match_prefers_the_official_video():
    assert videos.best_match(RESULTS, "YUNGBLUD", "parents", 172)["id"] == "official"


def test_video_match_rejects_lyric_videos_and_art_tracks():
    only_bad = [r for r in RESULTS if r["id"] in ("lyric1", "art", "fan")]
    assert videos.best_match(only_bad, "YUNGBLUD", "parents", 172) is None
    # A song with "Live" in its own title may match a live video.
    live = [{"id": "l", "title": "Band - Song (Live)", "channel": "Band", "duration": 200, "view_count": 1000}]
    assert videos.best_match(live, "Band", "Song (Live)", 200)["id"] == "l"


def test_video_endpoint_caches_answers(client, monkeypatch):
    login(client)
    client.app.state.cfg.music_videos = True
    t = all_tracks(client)
    calls = []

    def fake(artist, title):
        calls.append(title)
        return [{"id": "vid123", "title": f"{artist} - {title} (Official Music Video)", "channel": artist, "duration": 2, "view_count": 10}]

    monkeypatch.setattr(videos, "_search", fake)
    r = client.get(f"/api/tracks/{t['Opening']['id']}/video").json()
    assert r == {"found": True, "videoId": "vid123", "title": "Band - Opening (Official Music Video)", "channel": "Band"}
    client.get(f"/api/tracks/{t['Opening']['id']}/video")
    assert calls == ["Opening"]


def test_video_lookup_off(client):
    login(client)
    t = all_tracks(client)
    assert client.get(f"/api/tracks/{t['Opening']['id']}/video").json() == {"found": False}
