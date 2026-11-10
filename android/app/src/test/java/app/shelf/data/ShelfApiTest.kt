package app.shelf.data

import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.OkHttpClient
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test

class ShelfApiTest {
    private val server = MockWebServer()
    private var token: String? = null
    private lateinit var api: ShelfApi

    @Before fun setUp() {
        server.start(java.net.InetAddress.getByName("127.0.0.1"), 0)
        api = ShelfApi(server.url("/"), { token }, OkHttpClient())
    }

    @After fun tearDown() = server.close()

    private fun json(body: String, code: Int = 200) =
        server.enqueue(MockResponse.Builder().code(code).addHeader("Content-Type", "application/json").body(body).build())

    private fun fixture(name: String) = javaClass.classLoader!!.getResource("fixtures/$name")!!.readText()

    @Test fun pingReturnsVersion() = runTest {
        json("""{"app":"shelf","version":"0.6.0"}""")
        assertEquals("0.6.0", api.ping())
    }

    @Test fun pingRejectsNonShelf() = runTest {
        json("""{"app":"something-else"}""")
        try { api.ping(); fail("should throw") } catch (e: ShelfError.NotShelf) { }
    }

    @Test fun loginSendsJsonAndStoresToken() = runTest {
        json("""{"ok":true,"user":{"id":2,"username":"Listener","admin":true},"token":"tok123"}""")
        val (tok, user) = api.login("Listener", "pw")
        assertEquals("tok123", tok)
        assertEquals("Listener", user.username)
        val req = server.takeRequest()
        assertEquals("/api/login", req.url.encodedPath)
        val body = Json.parseToJsonElement(req.body!!.utf8()).jsonObject
        assertEquals("Listener", body["username"]!!.jsonPrimitive.content)
        assertEquals("pw", body["password"]!!.jsonPrimitive.content)
    }

    @Test fun requestsCarryBearerToken() = runTest {
        token = "abc"
        json(fixture("home.json"))
        api.home()
        assertEquals("Bearer abc", server.takeRequest().headers["Authorization"])
    }

    @Test fun unauthorizedIsSignedOut() = runTest {
        json("""{"detail":"Not signed in"}""", 401)
        try { api.home(); fail("should throw") } catch (e: ShelfError.SignedOut) { }
    }

    @Test fun serverErrorCarriesDetail() = runTest {
        json("""{"detail":"Too many tries. Try again in 15 minutes."}""", 429)
        try { api.login("a", "b"); fail("should throw") } catch (e: ShelfError.Server) {
            assertEquals(429, e.code)
            assertEquals("Too many tries. Try again in 15 minutes.", e.message)
        }
    }

    @Test fun networkFailureIsOffline() = runTest {
        server.close()
        try { api.home(); fail("should throw") } catch (e: ShelfError.Offline) { }
    }

    @Test fun parsesFixtures() = runTest {
        json(fixture("session.json")); assertTrue(api.session().signedIn)
        json(fixture("home.json")); assertTrue(api.home().added.isNotEmpty())
        json(fixture("albums.json")); assertTrue(api.albums().isNotEmpty())
        json(fixture("album.json")); val album = api.album(1); assertTrue(album.tracks.isNotEmpty()); assertEquals(album.trackCount, album.tracks.size)
        json(fixture("artist.json")); assertEquals("Black Sabbath", api.artist("Black Sabbath").name)
        json(fixture("artists.json")); assertTrue(api.artists().isNotEmpty())
        json(fixture("playlists.json")); assertTrue(api.playlists().isNotEmpty())
        json(fixture("playlist.json")); api.playlist(1)
        json(fixture("mixes.json")); val mixes = api.mixes(); assertTrue(mixes.isNotEmpty())
        json(fixture("mix.json")); assertTrue(api.mix(mixes[0].key).tracks.isNotEmpty())
        json(fixture("likes.json")); api.likes()
    }

    @Test fun artistNameIsEncoded() = runTest {
        json(fixture("artist.json"))
        api.artist("Aerosmith & Yungblud")
        assertEquals("Aerosmith & Yungblud", server.takeRequest().url.queryParameter("name"))
    }

    @Test fun coverUrlNullWithoutVersion() {
        assertNull(api.coverUrl(5, null, 320))
        assertEquals(server.url("/api/albums/5/cover?size=320&v=abc").toString(), api.coverUrl(5, "abc", 320))
    }

    @Test fun streamUrlCarriesQuality() {
        assertEquals(server.url("/api/tracks/7/stream?q=high").toString(), api.streamUrl(7, "high"))
    }

    @Test fun normalizeServerCases() {
        assertEquals("http://192.168.1.20:4533", normalizeServer("192.168.1.20:4533"))
        assertEquals("https://x.ts.net", normalizeServer("https://x.ts.net/"))
        assertEquals("http://shelf.home/music", normalizeServer(" shelf.home/music/index.html "))
        assertNull(normalizeServer("ftp://x"))
        assertNull(normalizeServer(""))
        assertNull(normalizeServer("http://"))
    }

    private fun summary(id: Int, name: String) = """{"id":$id,"name":"$name","trackCount":0,"duration":0,"covers":[],"canEdit":true}"""

    @Test fun createPlaylistSendsName() = runTest {
        json(summary(7, "Road trip"))
        assertEquals(7, api.createPlaylist("Road trip").id)
        val req = server.takeRequest()
        assertEquals("POST", req.method); assertEquals("/api/playlists", req.url.encodedPath)
        assertEquals("Road trip", Json.parseToJsonElement(req.body!!.utf8()).jsonObject["name"]!!.jsonPrimitive.content)
    }

    @Test fun addToPlaylistSendsTrackIds() = runTest {
        json(summary(7, "Road trip"))
        api.addToPlaylist(7, listOf(3, 4))
        val req = server.takeRequest()
        assertEquals("/api/playlists/7/tracks", req.url.encodedPath)
        assertEquals("[3,4]", Json.parseToJsonElement(req.body!!.utf8()).jsonObject["trackIds"].toString())
    }

    @Test fun reorderSendsEntryIdsInNewOrder() = runTest {
        assertEquals(listOf(20, 10, 30), moveItem(listOf(10, 20, 30), from = 1, to = 0))
        assertEquals(listOf(20, 30, 10), moveItem(listOf(10, 20, 30), from = 0, to = 2))
        json("""{"ok":true}""")
        api.reorderPlaylist(7, listOf(20, 10, 30))
        val req = server.takeRequest()
        assertEquals("PUT", req.method); assertEquals("/api/playlists/7/order", req.url.encodedPath)
        assertEquals("[20,10,30]", Json.parseToJsonElement(req.body!!.utf8()).jsonObject["entryIds"].toString())
    }

    @Test fun removeAndDeleteUseDelete() = runTest {
        json("""{"ok":true}"""); api.removeFromPlaylist(7, 99)
        server.takeRequest().let { assertEquals("DELETE", it.method); assertEquals("/api/playlists/7/tracks/99", it.url.encodedPath) }
        json("""{"ok":true}"""); api.deletePlaylist(7)
        server.takeRequest().let { assertEquals("DELETE", it.method); assertEquals("/api/playlists/7", it.url.encodedPath) }
    }

    @Test fun radioByTrackAndArtist() = runTest {
        json(fixture("mix.json")); api.radio(track = 12)
        assertEquals("12", server.takeRequest().url.queryParameter("track"))
        json(fixture("mix.json")); api.radio(artist = "Black Sabbath")
        assertEquals("Black Sabbath", server.takeRequest().url.queryParameter("artist"))
    }

    @Test fun playlistTracksCarryEntryIds() = runTest {
        json("""{"id":1,"name":"P","tracks":[{"id":5,"title":"T","artist":"A","albumId":2,"entryId":44}]}""")
        assertEquals(44, api.playlist(1).tracks.first().entryId)
    }

    @Test fun lyricsParseEveryKind() = runTest {
        json("""{"kind":"synced","lines":[{"t":1.5,"text":"Hello"}],"source":"file"}""")
        json("""{"kind":"plain","text":"Words","source":"lrclib"}""")
        json("""{"kind":"none","source":null,"searchedOnline":true}""")
        val synced = api.lyrics(7)
        assertEquals("/api/tracks/7/lyrics", server.takeRequest().url.encodedPath)
        assertEquals(listOf(LyricLine(1.5, "Hello")), synced.lines)
        assertEquals("Words", api.lyrics(7).text)
        assertEquals("none", api.lyrics(7).kind)
    }

    @Test fun videoParses() = runTest {
        json("""{"found":true,"videoId":"abc123XYZ_-","title":"Dream On (Official Video)","channel":"Aerosmith"}""")
        json("""{"found":false}""")
        val v = api.video(7)
        assertEquals("/api/tracks/7/video", server.takeRequest().url.encodedPath)
        assertEquals("abc123XYZ_-", v.videoId)
        assertTrue(v.found)
        assertEquals(false, api.video(8).found)
    }

    @Test fun peopleAndBlend() = runTest {
        json("""[{"id":2,"username":"Sam","canBlend":true},{"id":3,"username":"Kit","canBlend":false}]""")
        json("""{"key":"blend-2","kind":"blend","name":"Listener + Sam","with":"Sam","description":"A Blend of your tastes. You’re a 72% taste match",
            "match":72,"color":"#d6336c","tracks":[{"id":5,"title":"A","artist":"B","albumId":1,"blendFor":"both"}],"covers":[],"trackCount":1}""")
        json("""[{"user":{"id":2,"username":"Sam"},"now":{"track":{"id":5,"title":"A","artist":"B","albumId":1},"playing":true,"context":{"label":"Rock","href":"#/mix/x"},"device":"Desk"},
            "last":null,"sort":1}]""")
        assertEquals(listOf("Sam" to true, "Kit" to false), api.people().map { it.username to it.canBlend })
        val b = api.blend(2)
        assertEquals("/api/blend/2", server.takeRequest().let { server.takeRequest() }.url.encodedPath)
        assertEquals("Listener + Sam", b.name); assertEquals(listOf(5), b.tracks.map { it.id })
        val a = api.activity().single()
        assertEquals("Sam", a.user.username); assertEquals("Desk", a.now!!.device); assertTrue(a.now!!.playing)
    }

    @Test fun privateBlendSaysSo() = runTest {
        json("""{"detail":"Kit keeps their listening to themselves"}""", code = 403)
        try { api.blend(3); fail("expected an error") } catch (e: ShelfError.Server) {
            assertEquals(403, e.code); assertEquals("Kit keeps their listening to themselves", e.message)
        }
    }

    @Test fun makePlaylistSendsPrompt() = runTest {
        json("""{"name":"Metal, high energy","understood":["Heavy Metal","high energy"],"trackIds":[4,8,15]}""")
        val made = api.makePlaylist("metal, high energy")
        val req = server.takeRequest()
        assertEquals("POST", req.method)
        assertEquals("/api/playlists/make", req.url.encodedPath)
        assertEquals("""{"prompt":"metal, high energy","size":30}""", req.body!!.utf8())
        assertEquals(MadePlaylist("Metal, high energy", listOf("Heavy Metal", "high energy"), listOf(4, 8, 15)), made)

        json("""{"name":"Mix","id":3,"trackCount":3}""")
        api.createPlaylist("Mix", listOf(4, 8, 15), description = "Made by Shelf: Heavy Metal.")
        assertEquals("""{"name":"Mix","trackIds":[4,8,15],"description":"Made by Shelf: Heavy Metal."}""", server.takeRequest().body!!.utf8())
    }

    @Test fun statsParse() = runTest {
        json("""{"period":"year","plays":3,"minutes":12,"songs":2,"artists":1,
            "topArtists":[{"name":"Band","plays":3,"minutes":12}],
            "topSongs":[{"id":4,"title":"Closer","artist":"Band","albumId":5,"duration":200,"plays":2}],
            "topAlbums":[{"id":5,"title":"First","artist":"Band","plays":3}],
            "topGenres":[{"name":"heavy metal","plays":3}],"hours":[0,0,0,0,0,0,0,0,0,0,0,0,3,0,0,0,0,0,0,0,0,0,0,0],
            "weekdays":[3,0,0,0,0,0,0],"busiestDay":{"date":"2026-11-10","plays":3},"currentStreak":1,"longestStreak":1,
            "newArtists":["Band"],"onThisDay":[],"years":[2026]}""")
        val s = api.stats("year", tzMinutes = 60)
        server.takeRequest().url.let { assertEquals("/api/stats?period=year&tz=60", it.encodedPath + "?" + it.encodedQuery) }
        assertEquals(2, s.topSongs.single().plays)
        assertEquals(3, s.topAlbums.single().plays)
        assertEquals(BusiestDay("2026-11-10", 3), s.busiestDay)
        assertEquals(listOf(2026), s.years)
    }

    @Test fun partyCalls() = runTest {
        json("""[{"host":{"id":1,"username":"admin"},"people":2,"joined":true,"mine":false}]""")
        assertEquals(PartySummary(ActivityUser(1, "admin"), people = 2, joined = true), api.parties().single())
        json("""{"host":{"id":1,"username":"admin"},"isHost":false,"joined":true,"members":["admin","sam"],
            "nowPlaying":{"id":4,"title":"Closer","artist":"Band","albumId":5},"playing":true,
            "upNext":[{"id":6,"title":"Late","artist":"Band","albumId":5}],"votes":1,"needed":2,"youVoted":true}""")
        server.takeRequest()
        val st = api.party(1)
        assertEquals("/api/party/1", server.takeRequest().url.encodedPath)
        assertEquals("Closer", st.nowPlaying?.title); assertEquals(listOf("admin", "sam"), st.members); assertEquals(2, st.needed)
        json("""{"added":1,"at":1}""")
        api.partyAdd(1, listOf(6))
        server.takeRequest().let { assertEquals("/api/party/1/add", it.url.encodedPath); assertEquals("""{"trackIds":[6]}""", it.body!!.utf8()) }
        json("""{"skipped":false,"votes":1,"needed":2}""")
        assertEquals(SkipVote(false, 1, 2), api.partySkip(1))
    }

    @Test fun playlistMixSwitch() = runTest {
        json("""{}""")
        api.setPlaylistMix(9, true)
        val req = server.takeRequest()
        assertEquals("PATCH", req.method)
        assertEquals("/api/playlists/9", req.url.encodedPath)
        assertEquals("""{"mix":true}""", req.body!!.utf8())
    }

    @Test fun setTransitionSendsBody() = runTest {
        json("""{"ok":true,"transition":{"preset":"swap","bars":4.0}}""")
        api.setTransition(9, 55, app.shelf.playback.TransitionChoice("swap", bars = 4.0))
        val req = server.takeRequest()
        assertEquals("PUT", req.method)
        assertEquals("/api/playlists/9/tracks/55/transition", req.url.encodedPath)
        assertEquals("""{"style":"swap","bars":4.0}""", req.body!!.utf8())
    }
}
