"""Podcasts: follow a show by its feed, see its episodes, play them as tracks (with their place
kept), and they never count as music plays."""

import io

import pytest

from shelf import podcasts
from shelf.db import session

FEED = "https://feed.podbean.com/someshow/feed.xml"
RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel>
  <title>Some Show</title>
  <link>https://someshow.podbean.com</link>
  <itunes:author>Sam &amp; Alex</itunes:author>
  <description>&lt;p&gt;Talk about &lt;b&gt;records&lt;/b&gt;.&lt;/p&gt;</description>
  <itunes:image href="https://pbcdn1.podbean.com/imglogo/someshow.jpg"/>
  <item>
    <title>Episode 1: Hello</title>
    <guid>ep-1</guid>
    <pubDate>Mon, 02 Nov 2026 08:00:00 +0000</pubDate>
    <enclosure url="https://mcdn.podbean.com/mf/web/ep1.mp3" length="1000" type="audio/mpeg"/>
    <itunes:duration>1:02:03</itunes:duration>
    <content:encoded><![CDATA[<p>First one.</p><p>With <a href="x">links</a>.</p>]]></content:encoded>
  </item>
  <item>
    <title>Episode 2: Again</title>
    <guid>ep-2</guid>
    <pubDate>Mon, 09 Nov 2026 08:00:00 +0000</pubDate>
    <enclosure url="https://mcdn.podbean.com/mf/web/ep2.m4a" length="2000" type="audio/x-m4a"/>
    <itunes:duration>2700</itunes:duration>
    <description>Second.</description>
  </item>
  <item>
    <title>A video</title>
    <guid>vid</guid>
    <enclosure url="https://example.com/v.mp4" type="video/mp4"/>
  </item>
</channel>
</rss>"""


def test_reading_a_feed():
    show = podcasts.parse(RSS)
    assert show["title"] == "Some Show" and show["author"] == "Sam & Alex"
    assert show["description"] == "Talk about records."
    assert show["image"] == "https://pbcdn1.podbean.com/imglogo/someshow.jpg"
    assert [e["title"] for e in show["episodes"]] == ["Episode 2: Again", "Episode 1: Hello"]  # newest first, no video
    one = show["episodes"][1]
    assert one["duration"] == 3723 and one["description"] == "First one.\nWith links."
    assert show["episodes"][0]["duration"] == 2700
    with pytest.raises(podcasts.FeedError):
        podcasts.parse(b"<html><body>hi</body></html>")
    with pytest.raises(podcasts.FeedError):
        podcasts.parse(b"<rss><channel><title>x</title></channel></rss>")  # nothing to play


def test_finding_the_feed_behind_a_link(monkeypatch):
    assert podcasts.feed_for("https://someshow.podbean.com/") == FEED
    assert podcasts.feed_for("https://someshow.podbean.com/e/episode-1/") == FEED
    monkeypatch.setattr(podcasts, "_itunes", lambda path, **p: {"results": [{"feedUrl": "https://x.example/rss"}]})
    assert podcasts.feed_for("https://podcasts.apple.com/gb/podcast/some-show/id12345") == "https://x.example/rss"

    pages = {"https://site.example/show": b'<html><head><link rel="alternate" type="application/rss+xml" href="/feed.xml"></head></html>',
             "https://site.example/feed.xml": RSS}
    monkeypatch.setattr(podcasts, "_read", lambda url, limit, headers=None, timeout=20: (pages[url], None))
    assert podcasts.feed_for("https://site.example/show") == "https://site.example/feed.xml"
    assert podcasts.feed_for("https://site.example/feed.xml") == "https://site.example/feed.xml"
    assert podcasts.looks_like_link("someshow.podbean.com/") and podcasts.looks_like_link("someshow.podbean.com")
    assert not podcasts.looks_like_link("the daily") and not podcasts.looks_like_link("Mr. Robot")


def test_only_the_public_internet():
    for url in ("http://127.0.0.1/feed", "http://localhost:4533/api/x", "http://192.168.1.1/rss", "file:///etc/passwd"):
        with pytest.raises(podcasts.FeedError):
            podcasts.check_url(url)


def login(c):
    assert c.post("/api/login", json={"username": "admin", "password": "hunter2"}).status_code == 200


@pytest.fixture
def feeds(monkeypatch):
    monkeypatch.setattr(podcasts, "_read", lambda url, limit, headers=None, timeout=20: (RSS, None))


def test_follow_a_show_and_play_an_episode(client, feeds, monkeypatch):
    login(client)
    show = client.post("/api/podcasts", json={"feedUrl": FEED}).json()
    assert show["title"] == "Some Show" and show["following"] and show["episodes"] == 2 and show["unplayed"] == 2
    ep = show["episodeList"][0]
    assert ep["kind"] == "episode" and ep["id"] >= podcasts.EP_BASE and ep["albumId"] >= podcasts.SHOW_BASE
    assert ep["artist"] == "Some Show" and ep["duration"] == 2700 and ep["codec"] == "aac"

    mine = client.get("/api/podcasts").json()
    assert [s["title"] for s in mine["shows"]] == ["Some Show"]
    assert mine["continue"] == []

    # Its place is kept like a long track's, and a play never counts as a music play.
    tid = ep["id"]
    assert client.put(f"/api/tracks/{tid}/resume", json={"position": 600}).status_code == 200
    assert client.get(f"/api/tracks/{tid}/resume").json() == {"position": 600}
    assert client.post(f"/api/tracks/{tid}/played").status_code == 200
    assert client.post(f"/api/tracks/{tid}/skipped").status_code == 200
    with session(client.app.state.cfg.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM plays").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 0
    assert [e["title"] for e in client.get("/api/podcasts").json()["continue"]] == ["Episode 2: Again"]
    assert client.get(f"/api/tracks/{tid}/lyrics").json()["kind"] == "none"
    assert client.get(f"/api/tracks/{tid}/similar").json() == []

    # Near the end is finished; it can be marked unheard again.
    client.put(f"/api/tracks/{tid}/resume", json={"position": 2690})
    page = client.get(f"/api/podcasts/{show['id']}").json()
    assert page["unplayed"] == 1 and page["episodeList"][0]["finished"] and page["episodeList"][0]["position"] == 0
    assert client.put(f"/api/podcasts/episodes/{ep['episodeId']}", json={"finished": False}).json()["finished"] is False
    assert client.get(f"/api/podcasts/{show['id']}").json()["unplayed"] == 2


def test_the_episode_streams_through_the_server(client, feeds, monkeypatch):
    login(client)
    ep = client.post("/api/podcasts", json={"feedUrl": FEED}).json()["episodeList"][1]
    asked = {}

    class Upstream(io.BytesIO):
        status = 206
        headers = __import__("email.message", fromlist=["Message"]).Message()

    up = Upstream(b"ID3audio")
    up.headers["Content-Type"] = "audio/mpeg"
    up.headers["Content-Range"] = "bytes 0-7/8"
    up.headers["Content-Length"] = "8"

    def open_url(url, headers=None, timeout=20):
        asked.update(url=url, headers=headers)
        return up
    monkeypatch.setattr(podcasts, "open_url", open_url)
    r = client.get(f"/api/tracks/{ep['id']}/stream", headers={"Range": "bytes=0-"})
    assert r.status_code == 206 and r.content == b"ID3audio" and r.headers["content-range"] == "bytes 0-7/8"
    assert asked == {"url": "https://mcdn.podbean.com/mf/web/ep1.mp3", "headers": {"Range": "bytes=0-"}}
    assert client.get(f"/api/tracks/{podcasts.EP_BASE + 999}/stream").status_code == 404


def test_shows_are_shared_and_go_when_nobody_follows(client, feeds):
    login(client)
    client.post("/api/users", json={"username": "sam", "password": "sam-pass"})
    from fastapi.testclient import TestClient
    sam = TestClient(client.app)
    assert sam.post("/api/login", json={"username": "sam", "password": "sam-pass"}).status_code == 200
    a = client.post("/api/podcasts", json={"feedUrl": FEED}).json()
    b = sam.post("/api/podcasts", json={"feedUrl": FEED}).json()
    assert a["id"] == b["id"]  # stored once
    client.delete(f"/api/podcasts/{a['id']}")
    assert client.get("/api/podcasts").json()["shows"] == []
    assert sam.get(f"/api/podcasts/{a['id']}").status_code == 200
    sam.delete(f"/api/podcasts/{a['id']}")
    assert sam.get(f"/api/podcasts/{a['id']}").status_code == 404


def test_search_by_name_or_link(client, monkeypatch, feeds):
    login(client)
    monkeypatch.setattr(podcasts, "_itunes", lambda path, **p: {"results": [
        {"collectionName": "Some Show", "artistName": "Sam", "feedUrl": FEED, "artworkUrl600": "https://i/x.jpg"},
        {"collectionName": "No feed"}]})
    r = client.get("/api/podcasts/search", params={"q": "some show"}).json()["results"]
    assert [x["title"] for x in r] == ["Some Show"] and not r[0]["following"]
    client.post("/api/podcasts", json={"feedUrl": FEED})
    r = client.get("/api/podcasts/search", params={"q": "someshow.podbean.com"}).json()["results"]
    assert r[0]["feedUrl"] == FEED and r[0]["following"] and r[0]["episodes"] == 2

    def gone(*a, **k):
        raise podcasts.FeedError("That link isn’t a podcast feed.")
    monkeypatch.setattr(podcasts, "feed_for", gone)
    assert "isn’t a podcast" in client.get("/api/podcasts/search", params={"q": "https://example.com/x"}).json()["error"]


def test_home_has_your_podcasts(client, feeds):
    login(client)
    assert "podcasts" not in [r["key"] for r in client.get("/api/home").json()["rows"]]
    show = client.post("/api/podcasts", json={"feedUrl": FEED}).json()
    client.put(f"/api/tracks/{show['episodeList'][1]['id']}/resume", json={"position": 300})
    row = next(r for r in client.get("/api/home").json()["rows"] if r["key"] == "podcasts")
    assert row["title"] == "Your podcasts" and row["episodes"][0]["title"] == "Episode 1: Hello"  # partway through first


def test_old_shows_still_reach_home_and_search(client, feeds):
    login(client)
    show = client.post("/api/podcasts", json={"feedUrl": FEED}).json()
    with session(client.app.state.cfg.db_path) as conn:  # both episodes a year old: nothing "new"
        conn.execute("UPDATE episodes SET published_at = published_at - 365 * 86400")
    row = next(r for r in client.get("/api/home").json()["rows"] if r["key"] == "podcasts")
    assert [e["title"] for e in row["episodes"]] == ["Episode 2: Again"]  # the newest you haven't heard

    r = client.get("/api/search", params={"q": "some show"}).json()
    assert [p["title"] for p in r["podcasts"]] == ["Some Show"]
    r = client.get("/api/search", params={"q": "again"}).json()
    assert [e["title"] for e in r["episodes"]] == ["Episode 2: Again"] and r["episodes"][0]["podcastId"] == show["id"]

    # Typing in the main search only looks online when online lookups are on.
    assert client.get("/api/podcasts/search", params={"q": "history", "live": 1}).json() == {"results": [], "off": True}
