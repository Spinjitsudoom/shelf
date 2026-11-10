package app.shelf.playback

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SleepTimerTest {
    private var now = 1_000_000L
    private var stops = 0
    private val timer = SleepTimer { now }.apply { onStop = { stops++ } }

    @Test fun fadesThenPauses() {
        timer.set(5)
        assertEquals(1f, timer.onTick(), 0f)
        now += 5 * 60_000 - 4_000 // 4 s left: halfway through the 8 s fade
        assertEquals(0.5f, timer.onTick(), 0.01f)
        assertEquals(0, stops)
        now += 4_000
        assertEquals("volume back for next time", 1f, timer.onTick(), 0f)
        assertEquals(1, stops)
        assertNull(timer.state.value)
    }

    @Test fun endOfSongFollowsSkips() {
        timer.endOfSong()
        assertTrue(timer.state.value!!.endOfSong)
        assertEquals("no fade for end of song", 1f, timer.onTick(), 0f)
        // Skipping doesn't count; the song that's playing reaching its end does.
        now += 600_000
        assertEquals(0, stops)
        timer.onSongEnded()
        assertEquals(1, stops)
        assertNull(timer.state.value)
        timer.onSongEnded()
        assertEquals("only once", 1, stops)
    }

    @Test fun cancelRestoresVolume() {
        timer.set(15)
        now += 15 * 60_000 - 2_000
        assertTrue(timer.onTick() < 1f)
        timer.cancel()
        assertEquals(1f, timer.onTick(), 0f)
        assertNull(timer.state.value)
        assertEquals(0, stops)
        assertFalse(timer.choices.isEmpty())
        assertEquals(listOf(5, 15, 30, 45, 60, 90), timer.choices)
    }
}
