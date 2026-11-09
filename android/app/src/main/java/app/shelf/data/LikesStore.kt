package app.shelf.data

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** The server's Favourites calls (ShelfApi, or a fake in tests). */
interface LikesApi {
    suspend fun likeIds(): List<Int>
    suspend fun like(trackId: Int)
    suspend fun unlike(trackId: Int)
}

/**
 * Which songs are Favourites, for every heart in the app. A tap changes the heart at once and
 * tells the server; if that fails, the heart goes back and [toggle]'s onError says so.
 */
class LikesStore(private val api: () -> LikesApi?, private val scope: CoroutineScope) {
    private val _ids = MutableStateFlow<Set<Int>>(emptySet())
    val ids: StateFlow<Set<Int>> = _ids

    suspend fun refresh() {
        val a = api() ?: return
        runCatching { a.likeIds() }.getOrNull()?.let { _ids.value = it.toSet() }
    }

    fun toggle(trackId: Int, onError: (String) -> Unit) {
        val a = api() ?: return
        val liked = trackId in _ids.value
        _ids.update { if (liked) it - trackId else it + trackId }
        scope.launch {
            try {
                if (liked) a.unlike(trackId) else a.like(trackId)
            } catch (e: Exception) {
                if (e is kotlinx.coroutines.CancellationException) throw e
                _ids.update { if (liked) it + trackId else it - trackId }
                onError("Couldn’t save that. Check the connection and try again.")
            }
        }
    }
}
