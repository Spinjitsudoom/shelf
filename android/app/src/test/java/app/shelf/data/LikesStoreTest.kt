package app.shelf.data

import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Test

class LikesStoreTest {
    private class FakeLikes(var offline: Boolean = false) : LikesApi {
        val gate = CompletableDeferred<Unit>()
        var server = mutableSetOf(1, 2)
        var waitForGate = false
        override suspend fun likeIds() = server.toList()
        override suspend fun like(trackId: Int) { if (waitForGate) gate.await(); if (offline) throw ShelfError.Offline(); server += trackId }
        override suspend fun unlike(trackId: Int) { if (waitForGate) gate.await(); if (offline) throw ShelfError.Offline(); server -= trackId }
    }

    @Test fun refreshLoadsIds() = runTest {
        val store = LikesStore({ FakeLikes() }, this)
        store.refresh()
        assertEquals(setOf(1, 2), store.ids.value)
    }

    /** The heart fills at once, before the server answers. */
    @Test fun toggleIsOptimistic() = runTest {
        val fake = FakeLikes().apply { waitForGate = true }
        val store = LikesStore({ fake }, this)
        store.refresh()
        store.toggle(3) {}
        assertEquals(setOf(1, 2, 3), store.ids.value)
        fake.gate.complete(Unit); advanceUntilIdle()
        assertEquals(setOf(1, 2, 3), fake.server)
    }

    /** No connection: the heart goes back and says so, never silently lost. */
    @Test fun likeRollsBackWhenOffline() = runTest {
        val store = LikesStore({ FakeLikes(offline = true) }, this)
        store.refresh()
        var error: String? = null
        store.toggle(2) { error = it }   // unlike
        advanceUntilIdle()
        assertEquals(setOf(1, 2), store.ids.value)
        assertEquals("Couldn’t save that. Check the connection and try again.", error)
    }
}
