package app.shelf.playback

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PlaybackErrorsTest {
    /** A song that won't play is skipped, but a queue where nothing plays stops instead of racing through. */
    @Test fun skipsFailedSongsUntilSeveralInARow() {
        val skip = ErrorSkip(limit = 3)
        assertTrue(skip.failed(hasNext = true))
        assertTrue(skip.failed(hasNext = true))
        assertFalse(skip.failed(hasNext = true)) // the third in a row: stop
        skip.played()
        assertTrue(skip.failed(hasNext = true)) // counting starts again once something plays
        assertFalse(ErrorSkip().failed(hasNext = false)) // the last song: nothing to skip to
    }

    /** The quality is picked as each song loads, so a queue made on mobile data plays the real files on Wi-Fi. */
    @Test fun qualityPickedWhenTheSongLoads() {
        val queued = "http://shelf:4533/api/tracks/7/stream?q=high#pick=flac"
        assertEquals("http://shelf:4533/api/tracks/7/stream?q=original", pickQuality(queued) { codec -> if (codec == "flac") "original" else "low" })
        assertEquals("http://shelf:4533/api/tracks/7/stream?q=low", pickQuality("http://shelf:4533/api/tracks/7/stream?q=high#pick=") { "low" })
        // Downloads (and anything else not marked) are left exactly as they are.
        val download = "http://shelf:4533/api/tracks/7/stream?q=veryhigh"
        assertEquals(download, pickQuality(download) { "original" })
    }

    @Test fun qualityOfAnAddress() {
        assertEquals("veryhigh", qualityIn("http://shelf:4533/api/tracks/1/stream?q=veryhigh"))
        assertEquals("original", qualityIn("http://shelf:4533/api/tracks/1/stream?x=1&q=original#pick=mp3"))
        assertNull(qualityIn("http://shelf:4533/api/albums/1/cover"))
    }
}
