package app.shelf.downloads

import androidx.media3.exoplayer.offline.Download
import app.shelf.data.ShelfError
import app.shelf.data.Track
import app.shelf.ui.browse.FakeLibrary
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

private fun t(id: Int, album: Int = 1) = Track(id = id, title = "Song $id", artist = "Band", albumId = album, duration = 100.0)

class DownloadIndexTest {
    @get:Rule val tmp = TemporaryFolder()
    private val album = Downloadable("album", 1, "First Album", "Band", "#2c4fd0", tracks = listOf(t(1), t(2), t(3)))
    private val playlist = Downloadable("playlist", 9, "Road trip", tracks = listOf(t(2), t(7, album = 4)))

    @Test fun indexRoundTrip() {
        val file = tmp.root.resolve("downloads.json")
        DownloadIndex(file).apply { add(album); add(playlist) }
        val again = DownloadIndex(file)
        assertEquals(listOf(album, playlist), again.all())
        assertTrue(again.isDownloaded("album", 1))
        assertFalse(again.isDownloaded("album", 2))
        // Adding the same collection again replaces it (a playlist that changed).
        again.add(playlist.copy(name = "Road trip 2"))
        assertEquals(2, again.all().size)
        assertEquals("Road trip 2", DownloadIndex(file).get("playlist", 9)!!.name)
    }

    @Test fun failedDownloadNotMarkedComplete() {
        val done = mapOf(1 to Download.STATE_COMPLETED, 2 to Download.STATE_COMPLETED, 3 to Download.STATE_COMPLETED)
        assertTrue(isComplete(album, done))
        assertFalse("one song failed", isComplete(album, done + (3 to Download.STATE_FAILED)))
        assertFalse("one song still downloading", isComplete(album, done + (2 to Download.STATE_DOWNLOADING)))
        assertFalse("one song never started", isComplete(album, done - 3))
        assertEquals(1f, progressOf(album, done, emptyMap()), 0.001f)
        // A failed song counts as not downloaded, so the collection never shows as finished.
        assertEquals(2f / 3f, progressOf(album, done + (3 to Download.STATE_FAILED), emptyMap()), 0.001f)
        assertEquals(2.5f / 3f, progressOf(album, done + (3 to Download.STATE_DOWNLOADING), mapOf(3 to 50f)), 0.001f)
    }

    @Test fun removeForgetsDownloadable() {
        val index = DownloadIndex(tmp.root.resolve("downloads.json")).apply { add(album); add(playlist) }
        // Song 2 is also in the playlist, so removing the album keeps it.
        assertEquals(setOf(1, 3), index.tracksOnlyIn("album", 1))
        index.remove("album", 1)
        assertFalse(index.isDownloaded("album", 1))
        assertEquals(listOf(playlist), DownloadIndex(tmp.root.resolve("downloads.json")).all())
        assertEquals(setOf(2, 7), index.tracksOnlyIn("playlist", 9))
    }

    @Test fun offlineFallsBackToDownloads() = runTest {
        val index = DownloadIndex(tmp.root.resolve("downloads.json")).apply { add(album); add(playlist); add(Downloadable("favourites", 0, "Favourites", tracks = listOf(t(3)))) }
        val offline = OfflineSource(FakeLibrary(failures = 100), index)
        assertEquals(listOf(1, 2, 3), offline.album(1).tracks.map { it.id })
        assertEquals("First Album", offline.album(1).title)
        assertEquals(listOf(2, 7), offline.playlist(9).tracks.map { it.id })
        assertEquals(listOf(3), offline.likes().map { it.id })
        assertEquals(listOf(9), offline.playlists().map { it.id })
        assertEquals(listOf(1), offline.albums().map { it.id })
        try { offline.album(5); fail("not downloaded: still offline") } catch (e: ShelfError.Offline) {}
        // Online, the server's answer wins.
        assertEquals("Road trip", OfflineSource(FakeLibrary(), index).playlist(9).name)
        assertEquals(3, OfflineSource(FakeLibrary(), index).likes().size)
    }
}
