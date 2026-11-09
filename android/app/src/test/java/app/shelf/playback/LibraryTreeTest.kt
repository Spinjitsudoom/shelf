package app.shelf.playback

import androidx.test.ext.junit.runners.AndroidJUnit4
import app.shelf.ui.browse.FakeLibrary
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class LibraryTreeTest {
    private val tree = LibraryTree { FakeLibrary() }

    @Test fun rootHasFiveSections() = runTest {
        val root = tree.children(LibraryTree.ROOT)
        assertEquals(listOf("home", "mixes", "playlists", "albums", "favourites"), root.map { it.mediaId })
        assertEquals(listOf("Home", "Mixes", "Playlists", "Albums", "Favourites"), root.map { it.mediaMetadata.title.toString() })
        assertTrue(root.all { it.mediaMetadata.isBrowsable == true })
        assertEquals(listOf("album:1"), tree.children("albums").map { it.mediaId })
        assertEquals(listOf("mix:daily-1"), tree.children("mixes").map { it.mediaId })
        assertEquals(listOf("playlist:9"), tree.children("playlists").map { it.mediaId })
    }

    @Test fun albumChildrenArePlayableTracks() = runTest {
        val tracks = tree.children("album:1")
        assertEquals(listOf("album:1|1", "album:1|2", "album:1|3"), tracks.map { it.mediaId })
        assertTrue(tracks.all { it.mediaMetadata.isPlayable == true })
        assertFalse(tracks.first().mediaMetadata.isBrowsable == true)
        assertEquals(1, tracks.first().track()!!.id)
        assertEquals(PlayContext("First Album", "album/1"), tracks.first().playContext())
    }

    @Test fun playFromAlbumQueuesWholeAlbum() = runTest {
        val (items, index) = tree.expand("album:1|2")!!
        assertEquals(listOf(1, 2, 3), items.map { it.track()!!.id })
        assertEquals(1, index)
        assertEquals(listOf(1, 2, 3), tree.expand("favourites|3")!!.first.map { it.track()!!.id })
        assertEquals(null, tree.expand("album:1|99"))
    }
}
