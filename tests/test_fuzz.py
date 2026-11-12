"""Bad input never breaks the server: every Subsonic call, and the web API's main pages, given
nothing, nonsense and hostile values, answer with an error of their own instead of falling over."""

import itertools

from shelf.subsonic import Subsonic
from test_subsonic import setup

METHODS = sorted(n[2:] for n in dir(Subsonic) if n.startswith("m_"))
JUNK = ["", "0", "-1", "999999999999999999999", "al-", "ar-", "al-x", "ar-!!", "pc-9", "pe-x", "rs-0", "1e9",
        "' OR 1=1 --", "%", "_", "\\", "../../etc/passwd", "\x00", "🎵" * 50, "a" * 5000, "true", "null", "[]"]
PARAMS = ["id", "albumId", "artistId", "songId", "playlistId", "query", "type", "size", "offset", "count",
          "genre", "username", "password", "url", "name", "streamUrl", "message", "since", "expires", "position",
          "current", "currentIndex", "mediaId", "mediaType", "positionMs", "state", "startSongId", "endSongId",
          "musicFolderId", "artist", "title", "rating", "fromYear", "toYear", "format", "maxBitRate", "timeOffset",
          "transcodeParams", "songIndexToRemove", "songIdToAdd", "description", "action", "submission", "time"]


def ok_answer(r, label):
    assert r.status_code < 500, (label, r.status_code, r.text[:300])
    if r.headers.get("content-type", "").startswith("application/json"):
        body = r.json()["subsonic-response"]
        assert body["status"] in ("ok", "failed"), label
        if body["status"] == "failed":
            assert isinstance(body["error"]["code"], int), label


def test_every_call_with_nothing(client):
    sub = setup(client)
    for m in METHODS:
        ok_answer(sub.raw(m), m)


def test_every_call_with_junk(client):
    sub = setup(client)
    client.patch("/api/admin/shares", json={"enabled": True})
    junk = itertools.cycle(JUNK)
    for m in METHODS:
        if m in ("deleteUser", "changePassword", "updateUser"):
            continue  # changing accounts on purpose is tested elsewhere; here it would sign the test out
        for _ in range(4):
            params = {p: next(junk) for p in PARAMS}
            ok_answer(sub.raw(m, **params), f"{m} {params.get('id')!r}")
        for value in JUNK:
            ok_answer(sub.raw(m, id=value), f"{m} id={value!r}")


def test_hostile_values_on_the_web_api(client):
    assert client.post("/api/login", json={"username": "admin", "password": "hunter2"}).status_code == 200
    for value in JUNK:
        for path in ("/api/search?q={}", "/api/artist?name={}", "/api/albums/{}", "/api/tracks/{}/similar",
                     "/api/playlists/{}", "/api/podcasts/{}", "/api/mixes/{}", "/api/stats?period={}"):
            url = path.format(value.replace("\x00", "%00"))
            r = client.get(url)
            assert r.status_code < 500, (url, r.status_code, r.text[:200])
