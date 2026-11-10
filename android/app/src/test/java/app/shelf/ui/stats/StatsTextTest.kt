package app.shelf.ui.stats

import org.junit.Assert.assertEquals
import org.junit.Test

class StatsTextTest {
    @Test fun timeListened() {
        assertEquals("1 minute", hoursText(1))
        assertEquals("95 minutes", hoursText(95))
        assertEquals("15 hours", hoursText(886))
        assertEquals("1,234 hours", hoursText(74_040))
    }

    @Test fun whenYouListen() {
        val night = IntArray(24).also { it[23] = 5; it[1] = 5; it[14] = 3 }.toList()
        assertEquals("a night owl", listenerKind(night).first)
        val morning = IntArray(24).also { it[7] = 9; it[15] = 3 }.toList()
        assertEquals("an early bird", listenerKind(morning).first)
        val afternoon = IntArray(24).also { it[15] = 9; it[10] = 1 }.toList()
        assertEquals("most often listening around 3 pm", listenerKind(afternoon).first)
    }

    @Test fun streaks() {
        assertEquals("You’ve listened 12 days in a row. Your longest run this year: 31 days.", streakText(12, 31, "year"))
        assertEquals("You’ve listened today.", streakText(1, 1, "month"))
        assertEquals("No streak going right now. Your longest run in 2025: 9 days.", streakText(0, 9, "2025"))
    }
}
