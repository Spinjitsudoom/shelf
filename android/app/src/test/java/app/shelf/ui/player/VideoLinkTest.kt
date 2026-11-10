package app.shelf.ui.player

import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class VideoLinkTest {
    @Test fun appThenWebLinks() {
        val (app, web) = youtubeIntents("abc123XYZ_-", 95)
        assertEquals("vnd.youtube:abc123XYZ_-?t=95", app.dataString)
        assertEquals("https://www.youtube.com/watch?v=abc123XYZ_-&t=95s", web.dataString)
    }
}
