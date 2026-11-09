package app.shelf.ui.browse

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollToNode
import androidx.compose.ui.test.onNodeWithTag
import androidx.test.ext.junit.runners.AndroidJUnit4
import app.shelf.data.Album
import app.shelf.data.AlbumDetail
import app.shelf.data.ArtistPage
import app.shelf.data.ArtistSummary
import app.shelf.data.Home
import app.shelf.data.LibrarySource
import app.shelf.data.MixDetail
import app.shelf.data.MixSummary
import app.shelf.data.PlaylistDetail
import app.shelf.data.PlaylistSummary
import app.shelf.data.ShelfError
import app.shelf.data.Track
import app.shelf.playback.PlayContext
import app.shelf.ui.SignedOutHandler
import app.shelf.ui.theme.ShelfTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

private fun track(id: Int, title: String, album: Int = 1) = Track(id = id, title = title, artist = "Band", albumId = album, duration = 200.0, trackNo = id)

/** A library in memory; `failures` makes the next calls fail with "offline". */
class FakeLibrary(var failures: Int = 0) : LibrarySource {
    val album = AlbumDetail(1, "First Album", "Aerosmith & Yungblud", listOf("Aerosmith", "YUNGBLUD"), 2025, null, 3, 600.0, "#2c4fd0", null,
        listOf(track(1, "Opening"), track(2, "Middle"), track(3, "Closer")))
    private fun maybeFail() { if (failures > 0) { failures--; throw ShelfError.Offline() } }
    override suspend fun home() = Home(added = listOf(Album(1, "First Album", "Band")))
    override suspend fun albums(sort: String) = listOf(Album(1, "First Album", "Band"))
    override suspend fun album(id: Int): AlbumDetail { maybeFail(); return album }
    override suspend fun artists() = listOf(ArtistSummary("Band", 1, 3))
    override suspend fun artist(name: String) = ArtistPage(name, listOf(Album(1, "First Album", name)), album.tracks)
    override suspend fun playlists() = listOf(PlaylistSummary(9, "Road trip", trackCount = 2))
    override suspend fun playlist(id: Int) = PlaylistDetail(id, "Road trip", tracks = album.tracks.take(2))
    override suspend fun likes() = album.tracks
    override suspend fun mixes() = listOf(MixSummary("daily-1", "Shelf Mix 1", "Band and more", "#e8590c", "daily"))
    override suspend fun mix(key: String) = MixDetail(key, "Shelf Mix 1", tracks = album.tracks)
    override fun coverUrl(albumId: Int, version: String?, size: Int): String? = null
}

@RunWith(AndroidJUnit4::class)
class BrowseScreensTest {
    @get:Rule val rule = createComposeRule()
    private val noSignOut = SignedOutHandler {}

    @Test fun albumListsTracksInOrder() {
        rule.setContent { ShelfTheme { AlbumScreen(1, FakeLibrary(), { _, _, _ -> }, {}, {}, noSignOut) } }
        rule.waitUntil(5000) { rule.onAllNodesWithTag("track-title", useUnmergedTree = true).fetchSemanticsNodes().size == 3 }
        val titles = rule.onAllNodesWithTag("track-title", useUnmergedTree = true).fetchSemanticsNodes().map { it.config[androidx.compose.ui.semantics.SemanticsProperties.Text].joinToString() }
        assertEquals(listOf("Opening", "Middle", "Closer"), titles)
    }

    @Test fun tappingTrackPlaysFromIt() {
        var played: Triple<List<Track>, Int, PlayContext>? = null
        rule.setContent { ShelfTheme { AlbumScreen(1, FakeLibrary(), { t, i, c -> played = Triple(t, i, c) }, {}, {}, noSignOut) } }
        rule.waitUntil(5000) { rule.onAllNodesWithTag("track-title", useUnmergedTree = true).fetchSemanticsNodes().isNotEmpty() }
        rule.onNodeWithTag("tracks").performScrollToNode(hasText("Closer"))
        rule.onNodeWithText("Closer").performClick()
        assertEquals(2, played!!.second)
        assertEquals(3, played!!.first.size)
        assertEquals("First Album", played!!.third.label)
    }

    @Test fun errorStateRetries() {
        val lib = FakeLibrary(failures = 1)
        rule.setContent { ShelfTheme { AlbumScreen(1, lib, { _, _, _ -> }, {}, {}, noSignOut) } }
        rule.waitUntil(5000) { rule.onAllNodes(hasText("Try again")).fetchSemanticsNodes().isNotEmpty() }
        rule.onNodeWithText("Try again").performClick()
        rule.waitUntil(5000) { rule.onAllNodesWithTag("track-title", useUnmergedTree = true).fetchSemanticsNodes().size == 3 }
    }

    @Test fun artistLinksOpenEachArtist() {
        val opened = mutableListOf<String>()
        rule.setContent { ShelfTheme { AlbumScreen(1, FakeLibrary(), { _, _, _ -> }, { opened += it }, {}, noSignOut) } }
        // The credit keeps its own wording ("Yungblud"); the link opens the library's YUNGBLUD.
        rule.waitUntil(5000) { rule.onAllNodes(hasText("Yungblud") and hasClickAction()).fetchSemanticsNodes().isNotEmpty() }
        rule.onNode(hasText("Aerosmith") and hasClickAction()).performClick()
        rule.onNode(hasText("Yungblud") and hasClickAction()).performClick()
        assertEquals(listOf("Aerosmith", "YUNGBLUD"), opened)
    }

    @Test fun homeShowsMixTapes() {
        rule.setContent { ShelfTheme { HomeScreen(FakeLibrary(), "Listener", {}, {}, {}, noSignOut) } }
        rule.waitUntil(5000) { rule.onAllNodes(hasText("Shelf Mix 1")).fetchSemanticsNodes().isNotEmpty() }
        rule.onNodeWithText("Made for you").assertIsDisplayed()
    }
}
