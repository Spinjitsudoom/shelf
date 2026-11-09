package app.shelf.connect

import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.OkHttpClient
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.net.InetAddress
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

/** One server-side end of a connection: what the phone sent, and a way to answer. */
private class Hub : WebSocketListener() {
    val got = LinkedBlockingQueue<String>()
    @Volatile var ws: WebSocket? = null
    val opened = java.util.concurrent.CountDownLatch(1)
    override fun onOpen(webSocket: WebSocket, response: Response) { ws = webSocket; opened.countDown() }
    override fun onMessage(webSocket: WebSocket, text: String) { got.add(text) }
    override fun onClosing(webSocket: WebSocket, code: Int, reason: String) { webSocket.close(1000, null) }
    fun next(): String? = got.poll(3, TimeUnit.SECONDS)
    fun say(text: String) { opened.await(3, TimeUnit.SECONDS); ws!!.send(text) }
}

class ConnectClientTest {
    private val server = MockWebServer()
    private var now = 1_000_000L
    private val reconnects = LinkedBlockingQueue<() -> Unit>()
    private var savedId: String? = null
    private val identity = DeviceIdentity({ savedId }, { savedId = it }, "Redmi", "phone")
    private lateinit var client: ConnectClient

    private val welcome = """{"type":"welcome","you":"x","devices":[{"id":"pc12345678","name":"Desk","kind":"computer"},{"id":"ME","name":"Redmi","kind":"phone"}],
        "active":"pc12345678","state":{"index":0,"playing":true,"position":10},"queue":{"rev":1,"tracks":[{"id":1,"title":"A","artist":"B","albumId":2}]}}"""

    @Before fun setUp() {
        server.start(InetAddress.getByName("127.0.0.1"), 0)
        client = ConnectClient(identity, OkHttpClient(), { server.url("/").toString().trimEnd('/') },
            clock = { now }, post = { it.run() }, schedule = { _, r -> reconnects.add(r) })
    }

    @After fun tearDown() { client.stop(); server.close() }

    private fun hub(): Hub = Hub().also { server.enqueue(MockResponse.Builder().webSocketUpgrade(it).build()) }
    private fun welcomeFor(id: String) = welcome.replace("\"ME\"", "\"$id\"")
    private fun waitFor(what: () -> Boolean) { val end = System.currentTimeMillis() + 3000; while (!what() && System.currentTimeMillis() < end) Thread.sleep(10); assertTrue(what()) }

    @Test fun helloThenWelcomeFillsUi() {
        val h = hub()
        client.start()
        val hello = h.next()!!
        assertTrue(hello, hello.contains("\"type\":\"hello\"") && hello.contains("\"name\":\"Redmi\"") && hello.contains("\"kind\":\"phone\""))
        assertEquals(22, savedId!!.length)
        h.say(welcomeFor(savedId!!))
        waitFor { client.ui.value.connected }
        val ui = client.ui.value
        assertEquals("pc12345678", ui.activeId)
        assertTrue(ui.remote)
        assertEquals(listOf(1), ui.queue.map { it.id })
        assertEquals(10.0, ui.state!!.position, 0.0)
    }

    @Test fun heldCommandsSentAfterReconnect() {
        val h = hub()
        client.start(); h.next(); h.say(welcomeFor(savedId!!))
        waitFor { client.ui.value.connected }
        h.ws!!.close(1001, "going away")
        waitFor { !client.ui.value.connected }
        client.cmd("pause")
        val h2 = hub()
        reconnects.poll(3, TimeUnit.SECONDS)!!.invoke()
        assertTrue(h2.next()!!.contains("hello"))
        h2.say(welcomeFor(savedId!!))
        val sent = h2.next()
        assertTrue("$sent", sent!!.contains("\"type\":\"cmd\"") && sent.contains("\"name\":\"pause\""))
    }

    @Test fun staleCommandsDropped() {
        val h = hub()
        client.start(); h.next(); h.say(welcomeFor(savedId!!))
        waitFor { client.ui.value.connected }
        h.ws!!.close(1001, "going away")
        waitFor { !client.ui.value.connected }
        client.cmd("pause")
        now += 61_000
        val h2 = hub()
        reconnects.poll(3, TimeUnit.SECONDS)!!.invoke()
        h2.next()
        h2.say(welcomeFor(savedId!!))
        assertNull(h2.got.poll(600, TimeUnit.MILLISECONDS))
    }

    @Test fun duplicateTakesNewId() {
        val h = hub()
        client.start()
        h.next()
        val first = savedId
        val h2 = hub()
        h.say("""{"type":"duplicate"}""")
        val hello2 = h2.next()!!
        assertNotEquals(first, savedId)
        assertTrue(hello2.contains(savedId!!))
    }
}
