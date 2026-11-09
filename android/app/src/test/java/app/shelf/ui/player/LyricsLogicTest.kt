package app.shelf.ui.player

import app.shelf.data.LyricLine
import org.junit.Assert.assertEquals
import org.junit.Test

class LyricsLogicTest {
    private val lines = listOf(LyricLine(5.0, "one"), LyricLine(10.0, "two"), LyricLine(10.0, "two again"), LyricLine(20.0, "last"))

    @Test fun activeLineAtBoundaries() {
        assertEquals("before the first", -1, activeLine(lines, 4.99))
        assertEquals("exactly on a line", 0, activeLine(lines, 5.0))
        assertEquals("between lines", 0, activeLine(lines, 7.5))
        assertEquals("two at the same time: the later one", 2, activeLine(lines, 10.0))
        assertEquals("between, after the pair", 2, activeLine(lines, 15.0))
        assertEquals("after the last", 3, activeLine(lines, 999.0))
    }

    @Test fun emptyIsMinusOne() {
        assertEquals(-1, activeLine(emptyList(), 0.0))
        assertEquals(-1, activeLine(emptyList(), 50.0))
    }
}
