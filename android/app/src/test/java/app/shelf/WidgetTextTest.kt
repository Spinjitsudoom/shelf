package app.shelf

import app.shelf.data.Track
import org.junit.Assert.assertEquals
import org.junit.Test

class WidgetTextTest {
    private val t = Track(1, "Dream On", "Aerosmith", albumId = 2)

    @Test fun nothingPlaying() = assertEquals("Shelf" to "Tap to open", widgetText(null, null))
    @Test fun playingHere() = assertEquals("Dream On" to "Aerosmith", widgetText(t, null))
    @Test fun playingElsewhere() = assertEquals("Dream On" to "Aerosmith, on Desk", widgetText(t, "Desk"))
}
