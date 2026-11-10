package app.shelf.playback

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class QueueMoveTest {
    /** Six songs, the second playing: songs 3 to 6 are up next, and only they move, only among themselves. */
    @Test fun movesOnlyWithinUpNext() {
        assertEquals(2 to 5, queueMove(size = 6, current = 1, from = 2, to = 5))
        assertEquals(5 to 3, queueMove(6, 1, 5, 3))
        assertEquals("dropped above the playing song: first up next", 4 to 2, queueMove(6, 1, 4, 0))
        assertEquals("dropped past the end: last", 2 to 5, queueMove(6, 1, 2, 9))
        assertNull("the playing song stays", queueMove(6, 1, 1, 3))
        assertNull("played songs stay", queueMove(6, 1, 0, 3))
        assertNull("no move", queueMove(6, 1, 3, 3))
        assertNull("not in the queue", queueMove(6, 1, 6, 2))
    }
}
