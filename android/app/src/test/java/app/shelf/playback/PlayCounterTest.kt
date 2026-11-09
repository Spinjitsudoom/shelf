package app.shelf.playback

import org.junit.Assert.assertEquals
import org.junit.Test

class PlayCounterTest {
    private val played = mutableListOf<Int>()
    private val counter = PlayCounter { played += it }

    private fun listen(from: Int, to: Int) { for (s in from..to) counter.onPosition(s.toDouble()) }

    @Test fun countsOnlyHeardTime() {
        counter.onTrackStarted(1, 300.0)
        listen(0, 2)
        counter.onPosition(200.0) // a seek forward: not heard
        listen(201, 203)
        assertEquals(emptyList<Int>(), played)
    }

    @Test fun firesOnceAtHalfOrFourMinutes() {
        counter.onTrackStarted(1, 300.0)
        listen(0, 149); assertEquals(emptyList<Int>(), played)
        listen(150, 299); assertEquals(listOf(1), played) // half of 300 s, once
        counter.onTrackStarted(2, 600.0)
        listen(0, 239); assertEquals(listOf(1), played)
        listen(240, 400); assertEquals(listOf(1, 2), played) // four minutes, not half
    }

    @Test fun restartingTrackCountsAgain() {
        counter.onTrackStarted(7, 100.0); listen(0, 60)
        counter.onTrackStarted(7, 100.0); listen(0, 60)
        assertEquals(listOf(7, 7), played)
    }
}
