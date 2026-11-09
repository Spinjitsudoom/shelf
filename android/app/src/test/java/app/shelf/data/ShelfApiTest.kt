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
}
