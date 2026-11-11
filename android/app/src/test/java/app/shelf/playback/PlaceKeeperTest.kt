package app.shelf.playback

import app.shelf.data.Track
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PlaceKeeperTest {
    private val mix = Track(1, "Live at the Hall", "Band", albumId = 1, duration = 3600.0)
    private val other = Track(2, "Another Set", "Band", albumId = 1, duration = 2400.0)
    private val song = Track(3, "Single", "Band", albumId = 1, duration = 200.0)

    @Test fun onlyLongTracksKeepAPlace() {
        assertTrue(isLong(mix))
        assertFalse(isLong(song))
    }

    /** Every 15 seconds while it plays, when paused, and when it's left for another song. */
    @Test fun keepsThePlaceAsItPlays() {
        val sent = mutableListOf<Pair<Int, Double>>()
        val keeper = PlaceKeeper({ id, at -> sent += id to at })
        keeper.onPosition(mix, 100.0, nowMs = 0)
        keeper.onPosition(mix, 110.0, nowMs = 10_000)
        assertEquals(emptyList<Pair<Int, Double>>(), sent)
        keeper.onPosition(mix, 115.0, nowMs = 15_000)
        assertEquals(listOf(1 to 115.0), sent)
        keeper.onPosition(mix, 120.0, nowMs = 20_000)
        keeper.paused()
        assertEquals(1 to 120.0, sent.last())
        keeper.onPosition(mix, 121.0, nowMs = 21_000)
        keeper.leftFor(other)
        assertEquals(1 to 121.0, sent.last())
        val before = sent.size
        keeper.onPosition(song, 5.0, nowMs = 30_000) // a short song keeps nothing
        keeper.paused()
        assertEquals(before, sent.size)
    }
}
