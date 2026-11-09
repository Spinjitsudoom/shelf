package app.shelf.playback

import org.junit.Assert.assertEquals
import org.junit.Test

class StreamQualityTest {
    @Test fun wifiAlwaysOriginal() {
        assertEquals("original", streamQuality("flac", metered = false))
        assertEquals("original", streamQuality("mp3", metered = false))
    }

    /** On mobile data only big lossless files are made smaller; converting an MP3 saves little and makes it slow to start. */
    @Test fun mobileDataShrinksOnlyLossless() {
        assertEquals("high", streamQuality("flac", metered = true))
        assertEquals("high", streamQuality("ALAC", metered = true))
        assertEquals("original", streamQuality("mp3", metered = true))
        assertEquals("original", streamQuality("aac", metered = true))
        assertEquals("high", streamQuality(null, metered = true)) // unknown: play it safe on data
    }
}
