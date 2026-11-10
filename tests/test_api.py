def login(client):
    assert client.post("/api/login", json={"password": "hunter2"}).status_code == 200


def test_requires_login(client):
    assert client.get("/api/albums").status_code == 401
    assert client.post("/api/login", json={"password": "nope"}).status_code == 401
    assert client.get("/api/session").json()["signedIn"] is False
    login(client)
    assert client.get("/api/session").json()["signedIn"] is True


def test_albums_grouped_and_artists_merged(client):
    login(client)
    albums = client.get("/api/albums").json()
    assert sorted(a["title"] for a in albums) == ["First", "Second"]
    # "Band" and "band" folders collapse to one artist spelling
    assert len({a["artist"] for a in albums}) == 1
    second = next(a for a in albums if a["title"] == "Second")
    detail = client.get(f"/api/albums/{second['id']}").json()
    # Disc folders (including " Disc 1" with a stray space) merge into one album, in disc order
    assert [t["title"] for t in detail["tracks"]] == ["Early", "Late"]
    assert [t["discNo"] for t in detail["tracks"]] == [1, 2]


def test_cover_and_color(client):
    login(client)
    first = next(a for a in client.get("/api/albums").json() if a["title"] == "First")
    assert first["cover"] and first["color"]
    r = client.get(f"/api/albums/{first['id']}/cover?size=160")
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp"


def test_stream_original_supports_range(client):
    login(client)
    first = next(a for a in client.get("/api/albums").json() if a["title"] == "First")
    track = client.get(f"/api/albums/{first['id']}").json()["tracks"][0]
    r = client.get(f"/api/tracks/{track['id']}/stream", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and len(r.content) == 100
    assert r.headers["content-type"] == "audio/mpeg"


def test_stream_low_transcodes_to_aac(client):
    login(client)
    second = next(a for a in client.get("/api/albums").json() if a["title"] == "Second")
    track = client.get(f"/api/albums/{second['id']}").json()["tracks"][0]
    r = client.get(f"/api/tracks/{track['id']}/stream?q=low")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mp4"
    assert b"ftyp" in r.content[:16]


def test_search(client):
    login(client)
    res = client.get("/api/search?q=clos").json()
    assert [t["title"] for t in res["tracks"]] == ["Closer"]
    assert client.get("/api/search?q=second").json()["albums"][0]["title"] == "Second"


def test_rescan_picks_up_removals(client, library):
    login(client)
    (library / "Band" / "2001 - First" / "02 Closer.mp3").unlink()
    client.app.state.scanner.run_once()
    first = next(a for a in client.get("/api/albums").json() if a["title"] == "First")
    assert first["trackCount"] == 1


def test_plays_feed_home(client):
    login(client)
    first = next(a for a in client.get("/api/albums").json() if a["title"] == "First")
    track = client.get(f"/api/albums/{first['id']}").json()["tracks"][0]
    home = client.get("/api/home").json()
    assert home["recent"] == [] and len(home["added"]) == 2 and len(home["rediscover"]) == 2
    for _ in range(3):
        assert client.post(f"/api/tracks/{track['id']}/played").status_code == 200
    home = client.get("/api/home").json()
    assert [a["title"] for a in home["recent"]] == ["First"]
    assert home["top"][0]["plays"] == 3
    # Just-played albums aren't suggested for rediscovery
    assert [a["title"] for a in home["rediscover"]] == ["Second"]
    assert home["week"]["plays"] == 3


def test_tracks_report_bit_depth(client):
    login(client)
    second = next(a for a in client.get("/api/albums").json() if a["title"] == "Second")
    track = client.get(f"/api/albums/{second['id']}").json()["tracks"][0]
    assert track["codec"] == "flac" and track["bits"] == 16 and track["sampleRate"] == 44100


def test_loudness_measured_and_album_loudness(client):
    login(client)
    first = next(a for a in client.get("/api/albums").json() if a["title"] == "First")
    album = client.get(f"/api/albums/{first['id']}").json()
    # The fixture's scanner run measures loudness: ffmpeg's test tone (-18 dBFS peak) is about -22 LUFS.
    assert all(t["lufs"] is not None and -25 < t["lufs"] < -19 for t in album["tracks"])
    assert album["albumLufs"] is not None and album["albumPeak"] is not None


def test_quality_tiers(client):
    login(client)
    second = next(a for a in client.get("/api/albums").json() if a["title"] == "Second")
    track = client.get(f"/api/albums/{second['id']}").json()["tracks"][0]
    sizes = {}
    for q in ("low", "normal", "veryhigh"):
        r = client.get(f"/api/tracks/{track['id']}/stream?q={q}")
        assert r.status_code == 200 and r.headers["content-type"] == "audio/mp4"
        sizes[q] = len(r.content)
    assert sizes["low"] < sizes["veryhigh"]


def test_similar_history_storage(client):
    login(client)
    first = next(a for a in client.get("/api/albums").json() if a["title"] == "First")
    track = client.get(f"/api/albums/{first['id']}").json()["tracks"][0]
    sim = client.get(f"/api/tracks/{track['id']}/similar?limit=10").json()
    assert sim and all(t["id"] != track["id"] for t in sim)
    # Other albums by the artist come before the same album
    assert sim[0]["album"] != "First"
    client.post(f"/api/tracks/{track['id']}/played")
    assert client.delete("/api/history").json()["removed"] == 1
    assert client.get("/api/home").json()["recent"] == []
    client.get(f"/api/tracks/{track['id']}/stream?q=low")
    assert client.get("/api/storage").json()["transcodeBytes"] > 0
    assert client.post("/api/storage/clear").json()["freedBytes"] > 0
    assert client.get("/api/storage").json()["transcodeBytes"] == 0


def test_slow_requests_are_logged(client, caplog):
    """A request that takes long is named in the server log, so a stuck page can be traced."""
    import logging
    client.app.state.slow_after = 0.0  # everything counts as slow here
    with caplog.at_level(logging.WARNING, logger="shelf"):
        client.get("/api/ping")
    assert any("Slow request: GET /api/ping took" in r.getMessage() for r in caplog.records)
