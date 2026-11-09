package app.shelf

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.Request
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import org.junit.runner.RunWith
import java.net.InetAddress

@RunWith(AndroidJUnit4::class)
class AppContainerTest {
    /** The token goes to the chosen server and nowhere else (covers and music only come from it). */
    @Test
    fun okHttpSignsOnlyOurServer() {
        val ours = MockWebServer().apply { start(InetAddress.getByName("127.0.0.1"), 0) }
        val other = MockWebServer().apply { start(InetAddress.getByName("127.0.0.1"), 0) }
        repeat(1) { ours.enqueue(MockResponse.Builder().body("ok").build()); other.enqueue(MockResponse.Builder().body("ok").build()) }
        val c = AppContainer(ApplicationProvider.getApplicationContext())
        c.store.server = ours.url("/").toString().trimEnd('/')
        c.store.token = "secret"
        c.okHttp.newCall(Request.Builder().url(ours.url("/x")).build()).execute().close()
        c.okHttp.newCall(Request.Builder().url(other.url("/x")).build()).execute().close()
        assertEquals("Bearer secret", ours.takeRequest().headers["Authorization"])
        assertNull(other.takeRequest().headers["Authorization"])
        ours.close(); other.close()
    }
}
