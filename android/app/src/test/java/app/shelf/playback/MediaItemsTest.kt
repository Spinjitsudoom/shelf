package app.shelf.playback

import androidx.test.ext.junit.runners.AndroidJUnit4
import app.shelf.data.ShelfApi
import app.shelf.data.Track
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class MediaItemsTest {
    private val api = ShelfApi("http://192.168.1.20:4533/".toHttpUrl(), { null }, OkHttpClient())
    private val track = Track(12, "Wherever I May Roam", "Metallica", album = "The Black Album", albumId = 5, cover = "abc", duration = 404.0)
    private val ctx = PlayContext("The Black Album", "album/5")

    @Test fun mapsMetadataAndArtwork() {
        val item = track.toMediaItem(api, "original", ctx)
        assertEquals("12", item.mediaId)
        assertEquals("http://192.168.1.20:4533/api/tracks/12/stream?q=original", item.localConfiguration!!.uri.toString())
        assertEquals("Wherever I May Roam", item.mediaMetadata.title)
        assertEquals("Metallica", item.mediaMetadata.artist)
        assertEquals("The Black Album", item.mediaMetadata.albumTitle)
        assertEquals("http://192.168.1.20:4533/api/albums/5/cover?size=512&v=abc", item.mediaMetadata.artworkUri.toString())
        assertEquals(404_000L, item.mediaMetadata.durationMs)
    }

    @Test fun trackAndContextRoundTrip() {
        val item = track.toMediaItem(api, "high", ctx)
        assertEquals(track, item.track())
        assertEquals(ctx, item.playContext())
    }

    @Test fun downloadedSongPlaysFromItsDownload() {
        // A downloaded song plays from the address it was downloaded with (the copy on the phone), whatever the quality setting is now.
        val downloaded = "http://192.168.1.20:4533/api/tracks/12/stream?q=original"
        assertEquals(downloaded, track.toMediaItem(api, "low", ctx, downloaded).localConfiguration!!.uri.toString())
        assertEquals("http://192.168.1.20:4533/api/tracks/12/stream?q=low", track.toMediaItem(api, "low", ctx, null).localConfiguration!!.uri.toString())
    }
}
