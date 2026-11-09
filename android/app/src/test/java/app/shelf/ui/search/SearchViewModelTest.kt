package app.shelf.ui.search

import app.shelf.data.Album
import app.shelf.data.SearchResults
import app.shelf.ui.common.Load
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.delay
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class SearchViewModelTest {
    private val dispatcher = StandardTestDispatcher()
    private val asked = mutableListOf<String>()

    @Before fun setUp() = Dispatchers.setMain(dispatcher)
    @After fun tearDown() = Dispatchers.resetMain()

    private fun results(q: String) = SearchResults(albums = listOf(Album(1, q, "Band")))

    @Test fun debouncesTyping() = runTest(dispatcher) {
        val vm = SearchViewModel { q -> asked += q; results(q) }
        vm.onQuery("m"); advanceTimeBy(100)
        vm.onQuery("me"); advanceTimeBy(100)
        vm.onQuery("met"); advanceUntilIdle()
        assertEquals(listOf("met"), asked)
        assertEquals("met", ((vm.results.value as Load.Ready).value.albums.first().title))
    }

    /** A slow answer to an older search never replaces the newer one's. */
    @Test fun staleResultsIgnored() = runTest(dispatcher) {
        val vm = SearchViewModel { q -> if (q == "slow") delay(5_000); results(q) }
        vm.onQuery("slow"); advanceTimeBy(400)   // asked, waiting on the server
        vm.onQuery("fast"); advanceUntilIdle()
        assertEquals("fast", ((vm.results.value as Load.Ready).value.albums.first().title))
    }

    @Test fun blankQueryShowsNothing() = runTest(dispatcher) {
        val vm = SearchViewModel { q -> results(q) }
        vm.onQuery("met"); advanceUntilIdle()
        vm.onQuery("   "); advanceUntilIdle()
        assertNull(vm.results.value)
    }
}
