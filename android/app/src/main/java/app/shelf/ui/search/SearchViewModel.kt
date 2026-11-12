package app.shelf.ui.search

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.shelf.data.SearchResults
import app.shelf.data.ShelfError
import app.shelf.ui.common.Load
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

/** Search as you type: asks once typing pauses (250 ms), and only the latest search's answer shows. */
class SearchViewModel(private val search: suspend (String) -> SearchResults) : ViewModel() {
    private val _query = MutableStateFlow("")
    val query: StateFlow<String> = _query
    private val _results = MutableStateFlow<Load<SearchResults>?>(null)
    val results: StateFlow<Load<SearchResults>?> = _results
    private var job: Job? = null

    /** The same search again (after something in its results changed). */
    fun refresh() = onQuery(_query.value)

    fun onQuery(q: String) {
        _query.value = q
        job?.cancel()
        if (q.isBlank()) { _results.value = null; return }
        job = viewModelScope.launch {
            delay(250)
            if (_results.value !is Load.Ready) _results.value = Load.Loading
            val r = try {
                Load.Ready(search(q.trim()))
            } catch (e: ShelfError) {
                Load.Failed(e)
            }
            ensureActive()
            if (_query.value == q) _results.value = r
        }
    }
}
