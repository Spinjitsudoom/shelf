package app.shelf.playback

import androidx.media3.common.C
import app.shelf.data.Track
import org.junit.Assert.assertEquals
import org.junit.Test

class ShownDurationTest {
    private val song = Track(1, "Last Ride In", "Green Day", albumId = 80, duration = 227.5)

    @Test fun theStreamsOwnLengthWins() = assertEquals(226_900L, shownDuration(226_900, song))

    @Test fun aConvertedStreamThatCantSayUsesTheLibrarys() {
        // A song converted as it's sent has no length in it: the bar would sit at 0:00.
        assertEquals(227_500L, shownDuration(C.TIME_UNSET, song))
        assertEquals(227_500L, shownDuration(0, song))
    }

    @Test fun nothingKnownAtAll() = assertEquals(0L, shownDuration(C.TIME_UNSET, null))
}
