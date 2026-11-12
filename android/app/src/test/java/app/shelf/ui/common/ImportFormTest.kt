package app.shelf.ui.common

import app.shelf.data.ImportResult
import app.shelf.data.ImportedPlaylist
import app.shelf.data.ImportedSong
import app.shelf.data.Track
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ImportFormTest {
    private fun song(want: String, id: Int? = null) =
        ImportedSong(want, id?.let { Track(id = it, title = "Song $it", artist = "Band", albumId = 1) })

    private val one = ImportResult(listOf(ImportedPlaylist("Road trip", 2, listOf(song("Band - A", 1), song("Nobody - X"), song("Band - A again", 1), song("Band - B", 2)))))

    @Test fun findsWithTheTextOrTheFile() = runTest {
        val asked = mutableListOf<Pair<String, String>>()
        val form = ImportForm()
        val onFind: suspend (String, String) -> ImportResult = { t, f -> asked += t to f; one }

        assertFalse(form.find(onFind))
        assertEquals("Paste a link or a list of songs, or choose a file.", form.error)

        form.chooseFile("list.m3u", "#EXTM3U\nBand - A")
        assertTrue(form.find(onFind))
        assertEquals("#EXTM3U\nBand - A" to "list.m3u", asked.last())
        assertEquals(one, form.result)

        form.back()
        form.type("https://open.spotify.com/playlist/abc")
        assertNull(form.file) // typing replaces the file
        assertTrue(form.find(onFind))
        assertEquals("https://open.spotify.com/playlist/abc" to "", asked.last())
    }

    @Test fun saysWhyItCouldNot() = runTest {
        val form = ImportForm()
        form.type("nothing")
        assertFalse(form.find { _, _ -> throw IllegalStateException("Shelf couldn’t find any songs in that.") })
        assertEquals("Shelf couldn’t find any songs in that.", form.error)
        assertFalse(form.working)
    }

    @Test fun makesEachPickedPlaylistOnceWithItsSongs() = runTest {
        val two = ImportResult(listOf(
            ImportedPlaylist("Road trip", 2, listOf(song("Band - A", 1), song("Nobody - X"), song("Band - A", 1), song("Band - B", 2))),
            ImportedPlaylist("Nothing here", 0, listOf(song("Nobody - Y"))),
            ImportedPlaylist("Gym", 1, listOf(song("Band - C", 3))),
        ), linked = false)
        val form = ImportForm()
        form.type("x")
        form.find { _, _ -> two }
        assertEquals(setOf(0, 2), form.picked) // the ones with songs found
        form.rename(2, "  Workout ")
        val made = mutableListOf<Triple<String, String, List<Int>>>()
        val ids = form.make { name, description, trackIds -> made += Triple(name, description, trackIds); made.size }
        assertEquals(listOf(1, 2), ids)
        assertEquals(Triple("Road trip", "Imported. 1 song wasn’t in the library.", listOf(1, 2)), made[0])
        assertEquals(Triple("Workout", "Imported.", listOf(3)), made[1])
    }

    @Test fun pickingNothingSaysSo() = runTest {
        val form = ImportForm()
        form.type("x")
        form.find { _, _ -> one }
        form.toggle(0)
        assertEquals(emptyList<Int>(), form.make { _, _, _ -> 1 })
        assertEquals("Pick at least one playlist.", form.error)
    }

    @Test fun aLinkSharedFromAnotherApp() {
        assertEquals("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=abc",
            sharedPlaylistLink("Check out Today’s Top Hits on Spotify! https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=abc"))
        assertEquals("https://youtube.com/playlist?list=PLx_1-a&si=q", sharedPlaylistLink("https://youtube.com/playlist?list=PLx_1-a&si=q"))
        assertEquals("https://music.youtube.com/playlist?list=OLAK5uy", sharedPlaylistLink("Listen: https://music.youtube.com/playlist?list=OLAK5uy"))
        assertNull(sharedPlaylistLink("https://open.spotify.com/track/abc")) // one song, not a playlist
        assertNull(sharedPlaylistLink("https://youtu.be/xyz"))
        assertNull(sharedPlaylistLink("just some words"))
    }
}
