from shelf import analysis, artists, videos
from shelf.db import session


def login(client):
    assert client.post("/api/login", json={"password": "hunter2"}).status_code == 200


def all_tracks(client):
    out = []
    for a in client.get("/api/albums").json():
        out += client.get(f"/api/albums/{a['id']}").json()["tracks"]
    return {t["title"]: t for t in out}


def test_camelot():
    assert analysis.normalize_key("Bb", "minor") == "B♭ minor"
    assert analysis.camelot("A minor") == "8A"
    assert analysis.camelot("C major") == "8B"
    assert analysis.camelot("F♯ major") == "2B"
    assert analysis.camelot(analysis.normalize_key("Eb", "minor")) == "2A"
    assert analysis.camelot_neighbours("12A") == {"12A", "1A", "11A", "12B"}
    assert analysis.camelot_neighbours("1B") == {"1B", "2B", "12B", "1A"}


def test_tempo_and_key_survive_rescans(client):
    login(client)
    db = client.app.state.cfg.db_path
    with session(db) as conn:
        conn.execute("UPDATE tracks SET bpm = 128.4, musical_key = 'A minor', rhythm_checked = 1")
    client.app.state.scanner.run_once()
    t = all_tracks(client)["Opening"]
    assert t["bpm"] == 128 and t["key"] == "A minor" and t["camelot"] == "8A"


def test_recommendations_fit_the_playlist(client):
    login(client)
    t = all_tracks(client)
    db = client.app.state.cfg.db_path
    with session(db) as conn:
        conn.execute("UPDATE tracks SET genre = 'Rock', bpm = 120, musical_key = 'A minor'")
        conn.execute("UPDATE tracks SET genre = 'Jazz', bpm = 70, musical_key = 'F♯ major' WHERE title = 'Early'")
    p = client.post("/api/playlists", json={"name": "Mix", "trackIds": [t["Opening"]["id"]]}).json()
    recs = client.get(f"/api/playlists/{p['id']}/recommendations").json()
    titles = [r["title"] for r in recs]
    assert "Opening" not in titles  # never what's already there
    assert titles[0] == "Closer"  # same artist, genre, tempo and key
    assert titles[-1] == "Early"  # nothing in common
    assert client.get(f"/api/playlists/{p['id']}/recommendations?seed=3").status_code == 200
    empty = client.post("/api/playlists", json={}).json()
    assert client.get(f"/api/playlists/{empty['id']}/recommendations").json() == []


def test_recommendations_reach_beyond_the_playlists_artists(client, library):
    """A metal playlist of two bands gets other metal bands suggested, not just more of those two."""
    from conftest import make_track
    bands = {"Metallica": 6, "Avenged Sevenfold": 6, "Slayer": 3, "Megadeth": 3, "Iron Maiden": 3, "Gojira": 3}
    for band, n in bands.items():
        for i in range(n):
            make_track(library / band / f"Album {i % 3}" / f"{i:02d} {band} {i}.mp3", title=f"{band} {i}",
                       artist=band, album=f"{band} album {i % 3}", track=i + 1)
    client.app.state.scanner.run_once()
    login(client)
    db = client.app.state.cfg.db_path
    with session(db) as conn:
        conn.execute("UPDATE tracks SET genre = 'Metal', bpm = 140")
        conn.execute("UPDATE tracks SET genre = 'Jazz', bpm = 80 WHERE title IN ('Opening', 'Closer', 'Late', 'Early')")
    t = all_tracks(client)
    seed = [t["Metallica 0"]["id"], t["Metallica 1"]["id"], t["Avenged Sevenfold 0"]["id"], t["Avenged Sevenfold 1"]["id"]]
    p = client.post("/api/playlists", json={"name": "Metal", "trackIds": seed}).json()
    recs = client.get(f"/api/playlists/{p['id']}/recommendations?limit=10").json()
    artists = [r["artist"] for r in recs]
    assert len(recs) == 10
    assert sum(a in ("Metallica", "Avenged Sevenfold") for a in artists) <= 2, artists
    assert {"Slayer", "Megadeth", "Iron Maiden", "Gojira"} <= set(artists), artists
    assert "Band" not in artists and "band" not in artists  # the jazz isn't suggested over the metal

    # With nothing else that fits, it still suggests more by the same bands rather than nothing.
    only = client.post("/api/suggest", json={"trackIds": [t["Opening"]["id"]], "limit": 3}).json()
    assert len(only) == 3


def test_artist_about_checks_it_is_a_musician(client, monkeypatch):
    login(client)
    client.app.state.cfg.artist_info = True
    pages = {
        "Slipknot": {"type": "standard", "title": "Slipknot", "description": "Type of knot", "extract": "A slipknot is a knot."},
        "Slipknot (band)": {"type": "standard", "title": "Slipknot (band)", "description": "American heavy metal band",
                            "extract": "Slipknot is an American heavy metal band.", "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Slipknot_(band)"}}},
    }
    monkeypatch.setattr(artists, "_summary", lambda title: pages.get(title))
    monkeypatch.setattr(artists, "_get_json", lambda url: {"query": {"search": []}})
    r = client.get("/api/artist/about", params={"name": "Slipknot"}).json()
    assert r["found"] and r["title"] == "Slipknot (band)" and r["image"] is None
    # A shared credit falls back to its first artist.
    r = client.get("/api/artist/about", params={"name": "Slipknot & Someone"}).json()
    assert r["found"] and r["title"] == "Slipknot (band)"
    assert client.get("/api/artist/about", params={"name": "Nobody Known"}).json() == {"found": False}


def test_artist_videos_keep_only_the_artists_own(client, monkeypatch):
    login(client)
    client.app.state.cfg.music_videos = True

    class FakeYDL:
        def __init__(self, *_a, **_k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def extract_info(self, *_a, **_k):
            return {"entries": [
                {"id": "a", "title": "Måneskin - CHOSEN (Official Video)", "channel": "Måneskin"},
                {"id": "b", "title": "Måneskin - CHOSEN (Lyrics)", "channel": "Lyric Land"},
                {"id": "c", "title": "Måneskin - MAMMAMIA (Official Video)", "channel": "ManeskinVEVO"},
                {"id": "d", "title": "Måneskin - I WANNA BE YOUR SLAVE (Live at Wembley)", "channel": "Måneskin"},
                {"id": "e", "title": "CHOSEN", "channel": "Måneskin - Topic"},
            ]}

    import yt_dlp
    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
    r = client.get("/api/artist/videos", params={"name": "Måneskin"}).json()
    assert [(v["videoId"], v["title"]) for v in r] == [("a", "CHOSEN"), ("c", "MAMMAMIA")]


def test_clean_title():
    assert videos.clean_title("YUNGBLUD - Parents (Official Video)", "YUNGBLUD") == "Parents"
    assert videos.clean_title("Slipknot - Duality [OFFICIAL VIDEO] [HD]", "Slipknot") == "Duality"


def test_tempo_is_measured(tmp_path):
    import subprocess
    f = tmp_path / "click.flac"
    # A click every half second (120 BPM) over a low A note, for 20 seconds.
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "aevalsrc='0.6*if(lt(mod(t,0.5),0.03),sin(2*PI*1500*t),0)+0.2*sin(2*PI*220*t)':s=44100:d=20",
                    str(f)], check=True)
    r = analysis.analyze(f)
    assert r is not None and abs(r["bpm"] - 120) <= 2


def test_artist_page(client, tmp_path):
    login(client)
    t = all_tracks(client)
    for _ in range(3):
        client.post(f"/api/tracks/{t['Closer']['id']}/played")
    client.post(f"/api/tracks/{t['Late']['id']}/played")
    p = client.post("/api/playlists", json={"name": "Mix", "trackIds": [t["Opening"]["id"], t["Closer"]["id"]]}).json()

    page = client.get("/api/artist?name=BAND").json()
    assert page["name"] in ("Band", "band")
    titles = [x["title"] for x in page["popular"]]
    assert titles[:2] == ["Closer", "Late"]  # most played first
    assert set(titles) == {"Opening", "Closer", "Late", "Early"}  # then the rest, never empty
    assert page["popular"][0]["plays"] == 3
    assert page["stats"]["plays"] == 4 and page["stats"]["songsPlayed"] == 2
    assert {a["kind"] for a in page["albums"]} == {"single"}  # two songs, a few seconds long
    assert [(x["id"], x["artistCount"]) for x in page["playlists"]] == [(p["id"], 2)]
    assert page["appearsOn"] == []
    assert client.get("/api/artist?name=Nobody").status_code == 404


def test_mix_points(tmp_path):
    import subprocess
    f = tmp_path / "song.flac"
    # 2 s of silence, a quiet 4 s intro, 40 s at full level, a 10 s fade-out, 3 s of silence.
    env = "if(lt(t,2),0,if(lt(t,6),0.15,if(lt(t,46),1,if(lt(t,56),(56-t)/10,0))))"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"aevalsrc='{env}*(0.6*if(lt(mod(t,0.5),0.03),sin(2*PI*1500*t),0)+0.2*sin(2*PI*220*t))':s=44100:d=59",
                    str(f)], check=True)
    r = analysis.analyze(f)
    m = r["mix"]
    assert abs(r["bpm"] - 120) <= 2
    assert 1.5 <= m["start"] <= 2.5 and 55 <= m["end"] <= 57
    assert 5 <= m["intro"] <= 7.5
    assert 48 <= m["outro"] <= 53
    assert 1.9 <= m["firstBeat"] <= 2.6
    assert abs(m["inPeriod"] - 0.5) < 0.03 and abs(m["outPeriod"] - 0.5) < 0.03
    assert m["outBeat"] <= m["outro"] and m["outro"] - m["outBeat"] < 1.5
    assert abs(((m["outBeat"] - m["firstBeat"]) / 0.5) % 1 - 0.5) > 0.4  # on the same beat grid


def test_likes_suggest_recent_and_mix(client):
    login(client)
    t = all_tracks(client)
    a, b = t["Opening"]["id"], t["Closer"]["id"]
    assert client.put(f"/api/likes/{a}").json() == {"liked": True}
    client.put(f"/api/likes/{a}")  # twice is fine
    client.put(f"/api/likes/{b}")
    assert client.get("/api/likes/ids").json() == [b, a]  # newest first
    assert [x["title"] for x in client.get("/api/likes").json()] == ["Closer", "Opening"]
    client.delete(f"/api/likes/{b}")
    assert client.get("/api/likes/ids").json() == [a]
    assert client.put("/api/likes/99999").status_code == 404

    s = client.post("/api/suggest", json={"trackIds": [a], "exclude": [b], "limit": 5}).json()
    ids = [x["id"] for x in s]
    assert a not in ids and b not in ids and len(ids) == 2

    client.post(f"/api/tracks/{b}/played")
    client.post(f"/api/tracks/{a}/played")
    assert [x["id"] for x in client.get("/api/tracks/recent").json()] == [a, b]

    p = client.post("/api/playlists", json={"name": "Set", "trackIds": [a, b]}).json()
    assert p["mix"] is False
    assert client.patch(f"/api/playlists/{p['id']}", json={"mix": True}).json()["mix"] is True
    entry = client.get(f"/api/playlists/{p['id']}").json()["tracks"][0]
    url = f"/api/playlists/{p['id']}/tracks/{entry['entryId']}/transition"
    assert entry["transition"] == {"preset": "auto"}
    assert client.put(url, json={"style": "swap"}).status_code == 200
    assert client.get(f"/api/playlists/{p['id']}").json()["tracks"][0]["transition"] == {"preset": "swap"}
    # Edited in the transition editor: the preset with its parts changed.
    edited = {"style": "blend", "filter": "rise", "bars": 4, "shift": -2}
    assert client.put(url, json=edited).json()["transition"] == {"preset": "blend", "filter": "rise", "bars": 4, "shift": -2}
    assert client.get(f"/api/playlists/{p['id']}").json()["tracks"][0]["transition"]["filter"] == "rise"
    assert client.put(url, json={"style": "wobble"}).status_code == 422
    assert client.put(url, json={"style": "blend", "eq": "loud"}).status_code == 422

    w = client.get(f"/api/tracks/{a}/peaks?start=0&end=2").json()
    assert len(w["full"]) == len(w["bass"]) > 30 and 0 <= min(w["full"]) <= max(w["full"]) <= 1
    assert 0.55 < max(w["full"]) < 0.7  # the test tone is a 440 Hz sine at -18 dB
    assert max(w["bass"]) < 0.3  # ... with nothing in the bass
