package app.shelf

import org.junit.Assert.assertEquals
import org.junit.Test

class SmokeTest {
    /** Until the switch-over, the native app installs beside the WebView app as its own app. */
    @Test
    fun appIdIsPreview() {
        assertEquals("app.shelf.preview", BuildConfig.APPLICATION_ID)
    }
}
