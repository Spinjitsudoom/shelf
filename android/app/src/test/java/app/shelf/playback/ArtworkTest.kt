package app.shelf.playback

import android.graphics.Bitmap
import androidx.core.net.toUri
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import app.shelf.AppContainer
import mockwebserver3.Dispatcher
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import mockwebserver3.RecordedRequest
import okio.Buffer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Test
import org.junit.runner.RunWith
import java.io.ByteArrayOutputStream
import java.net.InetAddress
import java.util.concurrent.TimeUnit

@RunWith(AndroidJUnit4::class)
class ArtworkTest {
    /** The notification, lock screen and car load covers themselves; the server only gives them to a signed-in request. */
    @Test
    fun artworkLoaderSendsTheSignIn() {
        val png = ByteArrayOutputStream().also { Bitmap.createBitmap(4, 4, Bitmap.Config.ARGB_8888).compress(Bitmap.CompressFormat.PNG, 100, it) }.toByteArray()
        val server = MockWebServer().apply {
            dispatcher = object : Dispatcher() {
                override fun dispatch(request: RecordedRequest) =
                    if (request.headers["Authorization"] == "Bearer tok") MockResponse.Builder().addHeader("Content-Type", "image/png").body(Buffer().write(png)).build()
                    else MockResponse.Builder().code(401).build()
            }
            start(InetAddress.getByName("127.0.0.1"), 0)
        }
        val c = AppContainer(ApplicationProvider.getApplicationContext())
        c.store.server = server.url("/").toString().trimEnd('/')
        c.store.token = "tok"
        val bitmap = artworkLoader(ApplicationProvider.getApplicationContext(), c.okHttp)
            .loadBitmap(server.url("/api/albums/1/cover?size=512&v=x").toString().toUri()).get(10, TimeUnit.SECONDS)
        assertNotNull(bitmap)
        assertEquals("Bearer tok", server.takeRequest().headers["Authorization"])
        server.close()
    }
}
