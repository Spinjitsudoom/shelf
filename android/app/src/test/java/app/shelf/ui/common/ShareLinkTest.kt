package app.shelf.ui.common

import org.junit.Assert.assertEquals
import org.junit.Test

class ShareLinkTest {
    /** What goes into the message app: what it is, the link, and how long it works. */
    @Test fun theMessageSays() {
        val url = "http://77.71.156.41:4533/s/abc"
        assertEquals("Listen to “Seize the Day” by Avenged Sevenfold: $url (the link works for a week)",
            shareText("track", "Seize the Day", "Avenged Sevenfold", url, days = 7))
        assertEquals("Listen to the album “City of Evil” by Avenged Sevenfold: $url (the link works for a week)",
            shareText("album", "City of Evil", "Avenged Sevenfold", url, days = 7))
        assertEquals("Listen to my playlist “Road trip”: $url (the link works for a week)",
            shareText("playlist", "Road trip", null, url, days = 7))
        assertEquals("Listen to “Seize the Day”: $url", shareText("track", "Seize the Day", "", url, days = null))
    }
}
