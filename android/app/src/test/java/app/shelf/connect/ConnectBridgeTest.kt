package app.shelf.connect

import android.os.Looper
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import app.shelf.data.Track
import app.shelf.playback.PlayContext
import app.shelf.playback.playContext
import app.shelf.playback.toControllerItem
import app.shelf.ui.browse.FakeLibrary
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Shadows.shadowOf

@RunWith(AndroidJUnit4::class)
class ConnectBridgeTest {
    private val exo = ExoPlayer.Builder(ApplicationProvider.getApplicationContext()).setLooper(Looper.getMainLooper()).build()
    private val link = FakeLink(remoteUi().copy(activeId = "me"))
    private var volume = 1f
    private var modes = mutableListOf<Boolean>()
    private val toItem = { t: Track, c: PlayContext? -> t.toControllerItem(FakeLibrary(), c).buildUpon().setUri("http://x/${t.id}").build() }
    private var private = false
    private val bridge = ConnectBridge(link, exo, toItem, onVolume = { volume = it }, onMode = { modes += it }, privateSession = { private })

    @After fun tearDown() = exo.release()

    private fun load(n: Int, ctx: PlayContext? = PlayContext("Album", "album/5")) =
        exo.setMediaItems((1..n).map { toItem(tr(it), ctx) })
    private fun idle() = shadowOf(Looper.getMainLooper()).idle()

    @Test fun reportHasWebShape() {
        load(2); exo.seekTo(1, 5000)
        bridge.report(forceQueue = true)
        val msg = link.sent.last()
        assertEquals("state", msg["type"]!!.jsonPrimitive.content)
        val s = msg["state"]!!.jsonObject
        assertEquals(1, s["index"]!!.jsonPrimitive.int)
        assertEquals(5.0, s["position"]!!.jsonPrimitive.double, 0.01)
        assertEquals(2, s["track"]!!.jsonObject["id"]!!.jsonPrimitive.int)
        assertEquals("off", s["repeat"]!!.jsonPrimitive.content)
        assertEquals("#/album/5", s["context"]!!.jsonObject["href"]!!.jsonPrimitive.content)
        assertEquals(2, msg["queue"]!!.jsonObject["tracks"]!!.jsonArray.size)
        bridge.report(forceQueue = false)
        assertFalse("queue only when it changed", link.sent.last().containsKey("queue"))
    }

    @Test fun commandsRunOnPlayer() {
        load(3)
        bridge.onCmd("jumpTo", JsonArray(listOf(JsonPrimitive(1)))); assertEquals(1, exo.currentMediaItemIndex)
        bridge.onCmd("seek", JsonArray(listOf(JsonPrimitive(30)))); assertEquals(30_000L, exo.currentPosition)
        bridge.onCmd("next", JsonArray(emptyList())); assertEquals(2, exo.currentMediaItemIndex)
        bridge.onCmd("toggleShuffle", JsonArray(emptyList())); assertTrue(exo.shuffleModeEnabled)
        bridge.onCmd("cycleRepeat", JsonArray(emptyList())); assertEquals(Player.REPEAT_MODE_ALL, exo.repeatMode)
        bridge.onCmd("setVolume", JsonArray(listOf(JsonPrimitive(1.5)))); assertEquals(1f, volume)
        bridge.onCmd("setVolume", JsonArray(listOf(JsonPrimitive(0.25)))); assertEquals(0.25f, volume)
        bridge.onCmd("removeAt", JsonArray(listOf(JsonPrimitive(0)))); assertEquals(2, exo.mediaItemCount)
        val opts = JsonObject(mapOf("context" to JsonObject(mapOf("label" to JsonPrimitive("Shelf Mix 1"), "href" to JsonPrimitive("#/mix/daily-1")))))
        bridge.onCmd("playList", JsonArray(listOf(tracksJson(listOf(tr(7), tr(8))), JsonPrimitive(1), opts)))
        assertEquals(2, exo.mediaItemCount); assertEquals(1, exo.currentMediaItemIndex); assertTrue(exo.playWhenReady)
        assertEquals(PlayContext("Shelf Mix 1", "mix/daily-1"), exo.currentMediaItem!!.playContext())
        bridge.onCmd("toggle", JsonArray(emptyList())); assertFalse(exo.playWhenReady)
    }

    @Test fun moveItemReordersUpNext() {
        load(4)
        bridge.onCmd("moveItem", JsonArray(listOf(JsonPrimitive(3), JsonPrimitive(1))))
        assertEquals(listOf("Song 1", "Song 4", "Song 2", "Song 3"), (0 until exo.mediaItemCount).map { exo.getMediaItemAt(it).mediaMetadata.title.toString() })
        bridge.onCmd("moveItem", JsonArray(listOf(JsonPrimitive(0), JsonPrimitive(2)))) // the playing song stays put
        assertEquals(0, exo.currentMediaItemIndex)
        assertEquals("Song 1", exo.getMediaItemAt(0).mediaMetadata.title)
    }

    @Test fun insertAtPutsPartySongsInPlace() {
        load(3)
        bridge.onCmd("insertAt", JsonArray(listOf(JsonPrimitive(1), tracksJson(listOf(tr(8), tr(9))))))
        assertEquals(listOf("Song 1", "Song 8", "Song 9", "Song 2", "Song 3"), (0 until exo.mediaItemCount).map { exo.getMediaItemAt(it).mediaMetadata.title.toString() })
        bridge.onCmd("insertAt", JsonArray(listOf(JsonPrimitive(0), tracksJson(listOf(tr(7)))))) // never before the playing song
        assertEquals("Song 7", exo.getMediaItemAt(1).mediaMetadata.title.toString())
        assertEquals(0, exo.currentMediaItemIndex)
    }

    @Test fun takeoverLoadsSnapshot() {
        bridge.onTakeover(Snapshot(listOf(tr(1), tr(2), tr(3)), 2, 42.0, true))
        assertEquals(3, exo.mediaItemCount); assertEquals(2, exo.currentMediaItemIndex)
        assertEquals(42_000L, exo.currentPosition); assertTrue(exo.playWhenReady)
    }

    @Test fun activeGoneTakesOverPaused() {
        val remote = remoteUi().copy(state = remoteUi().state!!.copy(playing = false))
        bridge.onUi(remote)
        assertEquals(listOf(true), modes)
        bridge.onUi(remote.copy(devices = remote.devices.filter { it.id != "pc" }))
        assertEquals(listOf(true, false), modes)
        assertEquals(3, exo.mediaItemCount); assertEquals(1, exo.currentMediaItemIndex)
        assertEquals(30_000L, exo.currentPosition); assertFalse(exo.playWhenReady)
    }

    @Test fun playingHereWhenAnotherIsActiveClaims() {
        load(2); exo.playWhenReady = true
        bridge.onUi(remoteUi())
        assertEquals("claim", link.sent.last()["type"]!!.jsonPrimitive.content)
        assertTrue("doesn't hand the controls over while it plays", modes.none { it })
    }

    @Test fun privateSessionIsReported() {
        load(1)
        bridge.report(forceQueue = false)
        assertEquals("false", link.sent.last()["state"]!!.jsonObject["private"].toString())
        private = true
        bridge.report(forceQueue = false)
        assertEquals("true", link.sent.last()["state"]!!.jsonObject["private"].toString())
    }
}
