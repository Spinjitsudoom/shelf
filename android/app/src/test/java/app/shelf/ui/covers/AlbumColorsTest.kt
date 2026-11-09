package app.shelf.ui.covers

import androidx.compose.ui.graphics.toArgb
import org.junit.Assert.assertEquals
import org.junit.Test

class AlbumColorsTest {
    private fun hex(argb: Int) = "#%06x".format(argb and 0xffffff)

    /** Same colours as the web app's fallbackColor() (src/shelf/web/js/util.js), worked out in Node. */
    @Test
    fun fallbackColorMatchesWeb() {
        assertEquals("#4d895f", hex(fallbackColor("Shelf").toArgb()))   // hue 138
        assertEquals("#81894d", hex(fallbackColor("Måneskin").toArgb())) // hue 68
    }

    @Test
    fun albumColorParsesHex() {
        assertEquals("#2c4fd0", hex(albumColor("#2c4fd0", "Anything").toArgb()))
        assertEquals("#4d895f", hex(albumColor(null, "Shelf").toArgb()))
        assertEquals("#4d895f", hex(albumColor("red", "Shelf").toArgb()))
    }
}
