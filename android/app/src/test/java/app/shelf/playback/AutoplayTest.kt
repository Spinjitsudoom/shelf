package app.shelf.playback

import app.shelf.data.Track
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class AutoplayTest {
    private fun t(id: Int) = Track(id, "Song $id", "Band", albumId = 1)

    @Test fun addsFreshSimilarSongs() {
        val queue = (1..300).toList()
        // 150 is among the last 200 played, so it's left out; 50 is older, so it can come back.
        val similar = listOf(t(150), t(50)) + (1000 until 1040).map(::t)
        val picked = autoplayPick(queue, similar, repeatOff = true)
        assertEquals(25, picked.size)
        assertEquals(50, picked.first().id)
        assertTrue(picked.none { it.id == 150 })
    }

    @Test fun noAutoplayWithRepeatOrOffline() {
        assertEquals(emptyList<Track>(), autoplayPick(listOf(1, 2), listOf(t(3)), repeatOff = false))
        assertEquals(emptyList<Track>(), autoplayPick(listOf(1, 2), emptyList(), repeatOff = true)) // offline: nothing came back
    }
}
