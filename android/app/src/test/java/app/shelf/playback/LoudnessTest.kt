package app.shelf.playback

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class LoudnessTest {
    /** The same rules as the web app (player.js _gainFor, settings.js LOUDNESS_TARGETS). */
    @Test fun gainMatchesWeb() {
        assertEquals(-6.0, gainDb(-8.0, -0.1, "normal"), 1e-9)       // -14 - (-8)
        assertEquals(2.0, gainDb(-25.0, -3.0, "quiet"), 1e-9)        // +6 wanted, but peaks stop it at -1 - (-3)
        assertEquals(6.0, gainDb(-17.0, -0.5, "loud"), 1e-9)         // loud doesn't hold back for peaks
        assertEquals(-24.0, gainDb(10.0, null, "normal"), 1e-9)      // never more than 24 dB down
        assertEquals(12.0, gainDb(-60.0, null, "loud"), 1e-9)        // nor 12 up
    }

    @Test fun nullLufsIsZero() = assertEquals(0.0, gainDb(null, -1.0, "normal"), 1e-9)

    @Test fun volumeNeverAboveOne() {
        assertEquals(1f, volumeFor(6.0), 1e-6f)
        assertEquals(0.5012f, volumeFor(-6.0), 1e-3f)
        assertTrue(volumeFor(-24.0) > 0f)
    }
}
