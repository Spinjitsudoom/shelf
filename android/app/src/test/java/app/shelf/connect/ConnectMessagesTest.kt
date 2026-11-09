package app.shelf.connect

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ConnectMessagesTest {
    private val track = """{"id":12,"title":"Song","artist":"Band","albumId":5,"duration":200.0,"path":"ignored","genre":"Rock"}"""

    @Test fun parsesEveryIncomingKind() {
        val w = parseIncoming("""{"type":"welcome","you":"me12345678","devices":[{"id":"pc12345678","name":"Desk","kind":"computer"}],"active":"pc12345678",
            "state":{"index":0,"track":$track,"playing":true,"position":12.5,"duration":200,"shuffle":false,"repeat":"all","context":{"label":"Album","href":"#/album/5"},"volume":0.8},
            "queue":{"rev":3,"tracks":[$track],"original":null}}""") as Incoming.Welcome
        assertEquals("me12345678", w.you)
        assertEquals(listOf(DeviceInfo("pc12345678", "Desk", "computer")), w.devices)
        assertEquals("pc12345678", w.active)
        assertEquals(12.5, w.state!!.position, 0.0)
        assertEquals(12, w.state!!.track!!.id)
        assertEquals("all", w.state!!.repeat)
        assertEquals(0.8, w.state!!.volume, 0.0)
        assertEquals(WebContext("Album", "#/album/5"), w.state!!.context)
        assertEquals(listOf(12), w.queue!!.map { it.id })

        assertEquals(Incoming.Devices(emptyList(), null), parseIncoming("""{"type":"devices","devices":[],"active":null}"""))
        val s = parseIncoming("""{"type":"state","state":{"index":1,"playing":false},"from":"pc12345678"}""") as Incoming.State
        assertEquals(1, s.state.index); assertNull(s.queue)
        val c = parseIncoming("""{"type":"cmd","name":"seek","args":[30]}""") as Incoming.Cmd
        assertEquals("seek", c.name); assertEquals(30.0, c.args[0].toString().toDouble(), 0.0)
        val t = parseIncoming("""{"type":"takeover","snapshot":{"queue":[$track],"index":0,"position":42,"playing":true,"shuffle":false,"repeat":"off","context":null}}""") as Incoming.Takeover
        assertEquals(42.0, t.snapshot.position, 0.0); assertTrue(t.snapshot.playing)
        assertEquals(Incoming.Release, parseIncoming("""{"type":"release"}"""))
        assertEquals(Incoming.Duplicate, parseIncoming("""{"type":"duplicate"}"""))
        assertEquals(Incoming.Notice("Hi"), parseIncoming("""{"type":"notice","text":"Hi"}"""))
        assertNull(parseIncoming("""{"type":"something new"}"""))
        assertNull(parseIncoming("not json"))
    }

    @Test fun smartShuffleIsOn() {
        val s = parseIncoming("""{"type":"state","state":{"index":0,"shuffle":"smart"}}""") as Incoming.State
        assertTrue(s.state.shuffle)
    }

    @Test fun routesAndHrefsMapBothWays() {
        assertEquals("#/album/5", webHref("album/5"))
        assertEquals("#/liked", webHref("favourites"))
        assertEquals("album/5", nativeRoute("#/album/5"))
        assertEquals("favourites", nativeRoute("#/liked"))
        assertEquals("artist/AC%2FDC", nativeRoute("#/artist/AC%2FDC"))
        assertNull(nativeRoute("#/"))
        assertNull(nativeRoute(null))
    }

    @Test fun transferMessageShape() {
        val m = transferMessage("pc12345678", Snapshot(listOf(app.shelf.data.Track(1, "A", "B", albumId = 2)), 0, 12.5, true, context = WebContext("Album", "#/album/2")))
        assertEquals("transfer", m["type"].toString().trim('"'))
        assertEquals("pc12345678", m["to"].toString().trim('"'))
        val snap = m["snapshot"] as kotlinx.serialization.json.JsonObject
        assertEquals("12.5", snap["position"].toString())
        assertEquals("#/album/2", (snap["context"] as kotlinx.serialization.json.JsonObject)["href"].toString().trim('"'))
        assertEquals(null, transferMessage("pc12345678", null)["snapshot"])
    }
}
