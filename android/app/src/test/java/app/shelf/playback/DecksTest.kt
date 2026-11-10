package app.shelf.playback

import android.os.Looper
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import app.shelf.data.Track
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Shadows.shadowOf

@RunWith(AndroidJUnit4::class)
class DecksTest {
    private fun deck() = ExoPlayer.Builder(ApplicationProvider.getApplicationContext()).setLooper(Looper.getMainLooper()).build()
    private val a = deck()
    private val b = deck()
    private val fx = mapOf<Player, ShelfAudioProcessor>(a to ShelfAudioProcessor(), b to ShelfAudioProcessor())
    private var planned: Plan? = Plan("fade", start = 100.0, length = 8.0, inStart = 0.0)
    private val swaps = mutableListOf<Player>()
    private val decks = Decks(a, b, { fx.getValue(it) }, planFor = { _, _, _, _ -> planned }, baseVolume = { 1f }).apply { onSwap = { swaps += it } }

    @After fun tearDown() { a.release(); b.release() }

    private fun item(id: Int) = Track(id, "Song $id", "Band", albumId = 1, duration = 200.0).toControllerItem(null as String?, null)
        .buildUpon().setUri("http://x/$id").build()
    private fun ids(p: Player) = (0 until p.mediaItemCount).map { p.getMediaItemAt(it).track()!!.id }
    private fun idle() = shadowOf(Looper.getMainLooper()).idle()
    private fun load(n: Int) { a.setMediaItems((1..n).map(::item)); a.seekTo(0, 100_000); a.playWhenReady = true; idle() }

    @Test fun handoverMovesTheQueue() {
        load(3)
        decks.tick(0)
        assertEquals(listOf(2), ids(b))
        assertSame(a, decks.current)
        decks.tick(4_000)
        assertTrue("both playing, mid-way", a.volume in 0.01f..0.99f && b.volume in 0.01f..0.99f)
        decks.tick(8_001)
        assertSame(b, decks.current)
        assertEquals(listOf(1, 2, 3), ids(b))
        assertEquals(1, b.currentMediaItemIndex)
        assertEquals(0, a.mediaItemCount)
        assertEquals(1f, b.volume)
        assertEquals(listOf<Player>(b), swaps)
    }

    @Test fun handoverKeepsQueueEdits() {
        load(3)
        decks.tick(0)
        a.addMediaItems(1, listOf(item(9))) // "play next" during the transition: [1, 9, 2, 3]
        a.removeMediaItem(3)                // and song 3 taken out: [1, 9, 2]
        idle()
        decks.tick(8_001)
        assertEquals(listOf(1, 2, 9), ids(b)) // what was put next plays after the song that's coming in
        assertEquals(1, b.currentMediaItemIndex)
    }

    @Test fun skipMidTransitionLeavesOneSong() {
        load(3)
        decks.tick(0)
        a.seekToNextMediaItem() // the person skips while the songs overlap
        idle()
        assertSame(b, decks.current)
        assertEquals(0, a.mediaItemCount)
        assertEquals(1f, b.volume)
        assertEquals(listOf(1, 2, 3), ids(b))
        assertEquals(1, b.currentMediaItemIndex)
    }

    @Test fun noTransitionWithoutNext() {
        load(1)
        decks.tick(0)
        assertEquals(0, b.mediaItemCount)
        assertSame(a, decks.current)
    }

    @Test fun listenersFollowTheNewDeck() {
        val seen = mutableListOf<Player>()
        decks.addListener(object : Player.Listener { override fun onEvents(player: Player, events: Player.Events) { seen += player } })
        load(3)
        decks.tick(0); idle()
        assertTrue("the incoming deck is quiet until it takes over", seen.none { it === b })
        decks.tick(8_001); idle()
        b.seekTo(2, 0); idle()
        assertSame(b, seen.last())
    }
}
