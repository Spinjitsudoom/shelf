package app.shelf.playback

import app.shelf.data.Track
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class QueueStoreTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun queueStoreRoundTrip() {
        val store = QueueStore(tmp.root.resolve("queue.json"))
        val snap = QueueSnapshot(
            tracks = listOf(Track(1, "One", "Band", albumId = 3, duration = 200.0), Track(2, "Måneskin 日本語", "Band", albumId = 3)),
            index = 1, positionMs = 42_000, context = PlayContext("First Album", "album/3"), shuffle = true, repeat = 2,
        )
        store.save(snap)
        assertEquals(snap, store.load())
    }

    @Test fun loadMissingFileIsNull() {
        assertNull(QueueStore(tmp.root.resolve("nope.json")).load())
    }

    @Test fun loadBrokenFileIsNull() {
        val f = tmp.root.resolve("broken.json").apply { writeText("{not json") }
        assertNull(QueueStore(f).load())
    }
}
