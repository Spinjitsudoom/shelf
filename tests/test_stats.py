"""Listening stats and the yearly Wrapped."""

import datetime as dt

from shelf import stats

UTC = dt.timezone.utc


def at(y, m, d, h=12):
    return dt.datetime(y, m, d, h, tzinfo=UTC).timestamp()


TRACKS = {
    1: {"id": 1, "artist": "Metallica", "album_artist_name": "Metallica", "album_id": 10, "duration": 300.0, "genre": "Metal"},
    2: {"id": 2, "artist": "Metallica", "album_artist_name": "Metallica", "album_id": 10, "duration": 240.0, "genre": "Metal"},
    3: {"id": 3, "artist": "Slayer", "album_artist_name": "Slayer", "album_id": 20, "duration": 180.0, "genre": "Thrash Metal"},
    4: {"id": 4, "artist": "Miles Davis", "album_artist_name": "Miles Davis", "album_id": 30, "duration": 600.0, "genre": "Jazz"},
}
genres_of = lambda t: {t["genre"].lower()}


def test_streaks():
    days = {100, 101, 102, 105, 106}
    assert stats.streaks(days, today=106) == (2, 3)  # current (105-106), longest (100-102)
    assert stats.streaks(days, today=107) == (2, 3)  # nothing yet today: yesterday's streak still counts
    assert stats.streaks(days, today=108) == (0, 3)
    assert stats.streaks(set(), today=5) == (0, 0)


def test_summary_of_a_year():
    plays = [(1, at(2026, 3, 1)), (1, at(2026, 3, 2)), (2, at(2026, 3, 3)), (3, at(2026, 3, 3, 23)),
             (1, at(2026, 6, 1)), (4, at(2025, 12, 31)), (3, at(2027, 1, 1))]
    s = stats.summary(plays, TRACKS, genres_of, tz_minutes=0, period="2026", now=at(2026, 11, 10))
    assert s["plays"] == 5 and s["songs"] == 3 and s["artists"] == 2
    assert s["minutes"] == round((300 * 3 + 240 + 180) / 60)
    assert s["topArtists"][0] == {"name": "Metallica", "plays": 4, "minutes": round((300 * 3 + 240) / 60)}
    assert [x["id"] for x in s["topSongs"]][:2] == [1, 2] and s["topSongs"][0]["plays"] == 3
    assert s["topAlbums"][0] == {"albumId": 10, "plays": 4}
    assert s["topGenres"][0] == {"name": "metal", "plays": 4}
    assert s["hours"][12] == 4 and s["hours"][23] == 1
    assert s["busiestDay"] == {"date": "2026-03-03", "plays": 2}
    assert s["longestStreak"] == 3  # 1 to 3 March
    assert s["newArtists"] == ["Metallica", "Slayer"]  # Miles Davis was first played in 2025


def test_local_time_moves_late_plays_to_the_next_day():
    plays = [(3, at(2026, 3, 3, 23))]
    s = stats.summary(plays, TRACKS, genres_of, tz_minutes=120, period="all", now=at(2026, 11, 10))
    assert s["hours"][1] == 1 and s["busiestDay"]["date"] == "2026-03-04"


def test_periods_and_on_this_day():
    now = at(2026, 11, 10)
    plays = [(1, at(2026, 11, 2)), (2, at(2026, 10, 30)), (4, at(2025, 11, 10, 9)), (3, at(2025, 11, 10, 20))]
    assert stats.summary(plays, TRACKS, genres_of, 0, "month", now)["plays"] == 1
    assert stats.summary(plays, TRACKS, genres_of, 0, "year", now)["plays"] == 2
    assert stats.summary(plays, TRACKS, genres_of, 0, "all", now)["plays"] == 4
    assert stats.on_this_day(plays, tz_minutes=0, now=now) == [4, 3]
    assert stats.years(plays, 0) == [2026, 2025]


def test_stats_endpoint(client):
    assert client.post("/api/login", json={"password": "hunter2"}).status_code == 200
    ids = {t["title"]: t["id"] for t in client.get("/api/tracks/random?limit=10").json()}
    for _ in range(2):
        client.post(f"/api/tracks/{ids['Closer']}/played")
    client.post(f"/api/tracks/{ids['Late']}/played")
    s = client.get("/api/stats?period=year&tz=60").json()
    assert s["plays"] == 3 and s["currentStreak"] == 1
    assert s["topSongs"][0]["title"] == "Closer" and s["topSongs"][0]["plays"] == 2
    assert s["topAlbums"][0]["title"] in ("First", "Second") and s["topAlbums"][0]["plays"] >= 1
    assert s["years"] and isinstance(s["onThisDay"], list)
    assert client.get("/api/stats?period=nonsense").status_code == 422
