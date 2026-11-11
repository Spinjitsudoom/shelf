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

    /** A phone with no FLAC decoder (Android 8.0) gets lossless files as a 320 kbps copy instead of as they are. */
    @Test fun undecodableLosslessComesAsACopy() {
        val noFlac = { mime: String -> mime != "audio/flac" }
        assertEquals("veryhigh", playableQuality("flac", "original", noFlac))
        assertEquals("veryhigh", playableQuality("FLAC", "original", noFlac))
        assertEquals("high", playableQuality("flac", "high", noFlac)) // a copy already
        assertEquals("original", playableQuality("mp3", "original", noFlac))
        assertEquals("original", playableQuality("aac", "original", noFlac))
        assertEquals("original", playableQuality(null, "original", noFlac))
        assertEquals("original", playableQuality("flac", "original") { true })
        assertEquals("veryhigh", playableQuality("alac", "original") { it != "audio/alac" })
    }
}
