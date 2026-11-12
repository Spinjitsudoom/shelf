"""Importing playlists from elsewhere: a Spotify or YouTube link, a playlist file from another
player (M3U, PLS, XSPF), a CSV export (Exportify, TuneMyMusic), Spotify's own data download, or a
pasted list of songs. Each song is looked up in the library; what isn't there is listed."""

import json

import pytest

from shelf import imports


def lib(*rows):
    out = []
    for i, r in enumerate(rows, 1):
        title, artist = r[0], r[1]
        extra = r[2] if len(r) > 2 else {}
        out.append({"id": i, "title": title, "artist": artist, "album_artist": extra.get("album_artist"),
                    "album": extra.get("album", "Album"), "duration": extra.get("duration", 200.0),
                    "path": extra.get("path", f"/music/{artist}/Album/{i:02d} {title}.flac")})
    return imports.Library(out)


LIB = lib(
    ("Bohemian Rhapsody", "Queen", {"duration": 355}),
    ("Bohemian Rhapsody", "The Braids", {"duration": 280}),
    ("Don't Stop Me Now", "Queen", {"duration": 209}),
    ("Intro", "The xx", {"duration": 128}),
    ("Intro", "M83", {"duration": 322}),
    ("Café del Mar", "Energy 52", {"duration": 420}),
    ("Lies (feat. Lana Del Rey)", "Zach Bryan", {"duration": 230}),
    ("Here Comes the Sun - Remastered 2009", "The Beatles", {"duration": 185}),
    ("Go", "The Chemical Brothers", {"duration": 260}),
    ("BELLAKEO", "Peso Pluma & Anitta", {"duration": 180}),
)


def want(**kw):
    return {"artist": "", "title": "", "album": "", "duration": None, "text": "", "path": ""} | kw


# ---------- finding songs in the library ----------

def test_same_title_picks_the_right_artist():
    assert LIB.find(want(artist="Queen", title="Bohemian Rhapsody")) == 1
    assert LIB.find(want(artist="The Braids", title="Bohemian Rhapsody")) == 2
    assert LIB.find(want(artist="M83", title="Intro")) == 5


def test_spelling_differences_dont_matter():
    assert LIB.find(want(artist="queen", title="Dont Stop Me Now")) == 3
    assert LIB.find(want(artist="Energy 52", title="Cafe Del Mar")) == 6
    assert LIB.find(want(artist="Beatles", title="Here Comes The Sun")) == 8  # "Remastered" and "The" aside
    assert LIB.find(want(artist="Zach Bryan, Lana Del Rey", title="Lies")) == 7  # Spotify's way


def test_a_song_by_someone_else_is_not_a_match():
    assert LIB.find(want(artist="Muse", title="Intro")) is None
    assert LIB.find(want(artist="Queen", title="Under Pressure")) is None


def test_a_line_of_text_in_either_order():
    assert LIB.find(want(text="Queen - Don't Stop Me Now")) == 3
    assert LIB.find(want(text="Don't Stop Me Now by Queen")) == 3
    assert LIB.find(want(text="The Chemical Brothers – Go")) == 9


def test_youtube_video_titles():
    # Noise around the song's name, and the channel standing in for the artist.
    assert LIB.find(want(text="BELLAKEO (Video Oficial) - Peso Pluma, Anitta", artist="Peso Pluma")) == 10
    assert LIB.find(want(text="Queen – Bohemian Rhapsody (Official Video Remastered)", artist="Queen Official")) == 1


def test_the_plain_song_over_a_live_one():
    both = lib(("Walk (Live)", "Avenged Sevenfold"), ("Walk", "Avenged Sevenfold"))
    assert both.find(want(text="Avenged Sevenfold - Walk (Official Video)")) == 2
    assert both.find(want(text="Avenged Sevenfold - Walk (Live)")) == 1


def test_near_spellings_of_the_same_song():
    gd = lib(("Basketcase", "Green Day"), ("Hitching A Ride", "Green Day"), ("Nightmare Theme", "Avenged Sevenfold"))
    assert gd.find(want(text="Green Day – Basket Case")) == 1
    assert gd.find(want(text="Green Day - Hitchin' a Ride (Official Video)")) == 2
    assert gd.find(want(artist="Green Day", title="Basket Case")) == 1
    assert gd.find(want(text="Avenged Sevenfold - Nightmare")) is None  # another song


def test_short_titles_need_the_whole_word():
    # "Go" inside "Gone" is not the song "Go".
    assert LIB.find(want(text="The Chemical Brothers - Gone Away")) is None


def test_a_file_path_from_another_player():
    assert LIB.find(want(path=r"D:\Music\Queen\Album\01 Bohemian Rhapsody.flac")) == 1


def test_duration_breaks_a_tie():
    two = lib(("Song", "Band", {"duration": 200}), ("Song", "Band", {"duration": 320, "album": "Live"}))
    assert two.find(want(artist="Band", title="Song", duration=318)) == 2
    assert two.find(want(artist="Band", title="Song", duration=201)) == 1


# ---------- reading playlists ----------

def test_m3u_with_extinf_and_paths():
    text = "#EXTM3U\n#PLAYLIST:Road trip\n#EXTINF:355,Queen - Bohemian Rhapsody\nD:\\Music\\x.mp3\n" \
           "#EXTINF:-1,M83 - Intro\nhttp://example.org/stream\n"
    [pl] = imports.parse_file(text, "trip.m3u8")
    assert pl["name"] == "Road trip"
    assert [s["text"] for s in pl["songs"]] == ["Queen - Bohemian Rhapsody", "M83 - Intro"]
    assert pl["songs"][0]["duration"] == 355 and pl["songs"][1]["duration"] is None
    assert pl["songs"][0]["path"] == "D:\\Music\\x.mp3"


def test_m3u_with_bare_paths_uses_the_folders():
    [pl] = imports.parse_file("Queen/A Night at the Opera/11 - Bohemian Rhapsody.mp3\n", "Favs.m3u")
    assert pl["name"] == "Favs"
    assert LIB.find(pl["songs"][0]) == 1


def test_exportify_csv():
    csv = ('"Track URI","Track Name","Album Name","Artist Name(s)","Release Date","Duration (ms)"\n'
           '"spotify:track:1","Bohemian Rhapsody","A Night at the Opera","Queen","1975-11-21","354320"\n'
           '"spotify:track:2","Lies (feat. Lana Del Rey)","Album","Zach Bryan,Lana Del Rey","2025","230000"\n')
    [pl] = imports.parse_file(csv, "my_road_trip.csv")
    assert pl["name"] == "my road trip"
    assert pl["songs"][0] | {} == want(artist="Queen", title="Bohemian Rhapsody", album="A Night at the Opera",
                                       duration=354.32)
    assert [LIB.find(s) for s in pl["songs"]] == [1, 7]


def test_tunemymusic_csv_with_several_playlists():
    csv = "Track name,Artist name,Album,Playlist name,Type,ISRC\n" \
          "Intro,The xx,xx,Chill,Playlist,X\nGo,The Chemical Brothers,Born,Gym,Playlist,Y\nIntro,M83,Hurry,Gym,Playlist,Z\n"
    pls = imports.parse_file(csv, "export.csv")
    assert [(p["name"], len(p["songs"])) for p in pls] == [("Chill", 1), ("Gym", 2)]


def test_spotify_data_download():
    data = {"playlists": [{"name": "Summer", "items": [
        {"track": {"trackName": "Go", "artistName": "The Chemical Brothers", "albumName": "Born"}},
        {"episode": {"episodeName": "A podcast"}},
        {"localTrack": {"uri": "spotify:local:Queen:A+Night:Bohemian+Rhapsody:354"}},
    ]}]}
    [pl] = imports.parse_file(json.dumps(data), "Playlist1.json")
    assert pl["name"] == "Summer"
    assert [LIB.find(s) for s in pl["songs"]] == [9, 1]
    liked = imports.parse_file(json.dumps({"tracks": [{"artist": "Queen", "album": "x", "track": "Don't Stop Me Now"}]}),
                               "YourLibrary.json")
    assert liked[0]["name"] == "Liked Songs" and LIB.find(liked[0]["songs"][0]) == 3


def test_xspf_and_pls():
    xspf = """<?xml version="1.0"?><playlist version="1" xmlns="http://xspf.org/ns/0/"><title>VLC list</title>
      <trackList><track><location>file:///m/a.flac</location><title>Intro</title><creator>The xx</creator>
      <duration>128000</duration></track></trackList></playlist>"""
    [pl] = imports.parse_file(xspf, "x.xspf")
    assert pl["name"] == "VLC list" and LIB.find(pl["songs"][0]) == 4
    pls = "[playlist]\nFile1=/m/Queen/x.mp3\nTitle1=Queen - Don't Stop Me Now\nLength1=209\nNumberOfEntries=1\n"
    [pl] = imports.parse_file(pls, "radio.pls")
    assert LIB.find(pl["songs"][0]) == 3


def test_a_pasted_list():
    [pl] = imports.parse_file("1. Queen - Don't Stop Me Now\n\n2) M83 – Intro\n- Go by The Chemical Brothers\n")
    assert [LIB.find(s) for s in pl["songs"]] == [3, 5, 9]
    assert pl["name"] == "Imported playlist"


def test_nothing_readable():
    assert imports.parse_file("   \n\n") == []


# ---------- Spotify and YouTube links ----------

def test_links_are_recognised():
    assert imports.link("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=abc") == \
        ("spotify", "https://open.spotify.com/embed/playlist/37i9dQZF1DXcBWIGoYBM5M")
    assert imports.link("https://open.spotify.com/intl-de/album/4aawyAB9vmqN3uQ7FjRGTy") == \
        ("spotify", "https://open.spotify.com/embed/album/4aawyAB9vmqN3uQ7FjRGTy")
    assert imports.link("https://music.youtube.com/playlist?list=PLabc_-1") == \
        ("youtube", "https://www.youtube.com/playlist?list=PLabc_-1")
    assert imports.link("https://www.youtube.com/watch?v=xyz&list=PLabc") == \
        ("youtube", "https://www.youtube.com/playlist?list=PLabc")
    assert imports.link("https://example.org/playlist/1") is None
    assert imports.link("Queen - Bohemian Rhapsody") is None


def test_spotify_page():
    page = {"props": {"pageProps": {"state": {"data": {"entity": {"name": "Today’s Top Hits", "trackList": [
        {"title": "Lies (feat. Lana Del Rey)", "subtitle": "Zach Bryan,\u00a0Lana Del Rey", "duration": 230000},
        {"title": "Unknown song", "subtitle": "Nobody", "duration": 100000}]}}}}}}
    html = f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(page)}</script></html>'
    pl = imports.parse_spotify(html)
    assert pl["name"] == "Today’s Top Hits"
    assert [LIB.find(s) for s in pl["songs"]] == [7, None]


def test_youtube_page():
    data = {"metadata": {"playlistMetadataRenderer": {"title": "Videos"}}, "contents": [
        {"lockupViewModel": {"contentType": "LOCKUP_CONTENT_TYPE_VIDEO", "metadata": {"lockupMetadataViewModel": {
            "title": {"content": "BELLAKEO (Video Oficial) - Peso Pluma, Anitta"},
            "metadata": {"contentMetadataViewModel": {"metadataRows": [
                {"metadataParts": [{"text": {"content": "Peso Pluma"}}]},
                {"metadataParts": [{"text": {"content": "776M"}}]}]}}}}}},
        {"playlistVideoRenderer": {"title": {"runs": [{"text": "Bohemian Rhapsody"}]},
                                   "shortBylineText": {"runs": [{"text": "Queen - Topic"}]}, "lengthSeconds": "355"}},
    ]}
    html = f"<script>var ytInitialData = {json.dumps(data)};</script>"
    pl = imports.parse_youtube(html)
    assert pl["name"] == "Videos"
    assert [LIB.find(s) for s in pl["songs"]] == [10, 1]


def test_a_page_without_a_playlist():
    with pytest.raises(ValueError):
        imports.parse_spotify("<html>nothing</html>")
    with pytest.raises(ValueError):
        imports.parse_youtube("<html>nothing</html>")


# ---------- through the server ----------

def login(c):
    assert c.post("/api/login", json={"username": "admin", "password": "hunter2"}).status_code == 200


def test_import_preview_through_the_server(client):
    login(client)
    r = client.post("/api/playlists/import", json={"text": "Band - Opening\nBand - Closer\nNobody - Nothing\n"})
    assert r.status_code == 200
    [pl] = r.json()["playlists"]
    assert [s["track"]["title"] if s["track"] else None for s in pl["songs"]] == ["Opening", "Closer", None]
    assert pl["found"] == 2 and pl["songs"][2]["want"] == "Nobody - Nothing"
    assert client.post("/api/playlists/import", json={"text": ""}).status_code == 400


def test_import_needs_a_sign_in(client):
    assert client.post("/api/playlists/import", json={"text": "Band - Opening"}).status_code == 401
