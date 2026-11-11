package app.shelf.ui.browse

import app.shelf.data.PlaylistDetail
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class PlaylistBylineTest {
    @Test fun smartPlaylistsShowTheirRules() {
        assertEquals("Songs never played.", playlistByline(null, "Songs never played"))
        assertEquals("For the gym\nSongs that fit Workout.", playlistByline("For the gym", "Songs that fit Workout"))
        assertEquals("Road trip songs", playlistByline("Road trip songs", null))
        assertNull(playlistByline(" ", null))
    }

    @Test fun rulesTextComesFromTheServer() {
        val json = Json { ignoreUnknownKeys = true }
        val p = json.decodeFromString<PlaylistDetail>(
            """{"id": 5, "name": "Old", "smart": {"match": "all"}, "rulesText": "Songs not played in 6 months", "canEdit": false}""")
        assertEquals("Songs not played in 6 months", p.rulesText)
    }
}
