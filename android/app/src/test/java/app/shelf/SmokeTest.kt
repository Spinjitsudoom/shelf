package app.shelf

import org.junit.Assert.assertEquals
import org.junit.Test

class SmokeTest {
    /** Shelf is app.shelf, so it updates the WebView app in place (Shelf Lite is app.shelf.lite; -Ppreview is app.shelf.preview). */
    @Test
    fun appIdIsShelf() {
        assertEquals("app.shelf", BuildConfig.APPLICATION_ID)
    }
}
