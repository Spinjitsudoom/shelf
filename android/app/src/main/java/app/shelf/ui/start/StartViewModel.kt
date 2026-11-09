package app.shelf.ui.start

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.shelf.data.ServerStore
import app.shelf.data.ShelfApi
import app.shelf.data.ShelfError
import app.shelf.data.normalizeServer
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * Getting in: which server, then who's listening. On launch with a saved sign-in it checks the
 * sign-in still works (and opens anyway with no connection, so downloads and errors show
 * in the app rather than a dead end).
 */
class StartViewModel(private val store: ServerStore, private val apiFor: (String) -> ShelfApi) : ViewModel() {
    enum class Step { Checking, Server, SignIn, Done }

    data class UiState(val step: Step = Step.Checking, val address: String = "", val busy: Boolean = false, val error: String? = null,
                       val note: String? = null)

    private val _state = MutableStateFlow(UiState(address = store.server?.let(::shown) ?: ""))
    val state: StateFlow<UiState> = _state

    /** How an address is shown: without "http://". */
    private fun shown(url: String) = url.replaceFirst(Regex("^https?://"), "")

    fun start() {
        val server = store.server
        if (server == null) { _state.update { it.copy(step = Step.Server) }; return }
        if (store.token == null) {
            // Installed over the WebView app: it saved the server, but its sign-in and downloads stayed in the web page.
            val note = if (!store.native) "Shelf has a new look. Sign in once more. Anything downloaded in the old app needs downloading again." else null
            _state.update { it.copy(step = Step.SignIn, note = note) }
            return
        }
        work {
            val signedIn = try { apiFor(server).session().signedIn } catch (e: ShelfError.Offline) { true }
            if (signedIn) {
                _state.update { it.copy(step = Step.Done) }
            } else {
                store.signOut()
                _state.update { it.copy(step = Step.SignIn) }
            }
        }
    }

    fun submitServer(input: String) {
        _state.update { it.copy(step = Step.Server, address = input, error = null) }
        val url = normalizeServer(input)
            ?: return fail("That doesn’t look like a server address. Try something like 192.168.1.20:4533.")
        work {
            val api = apiFor(url)
            try {
                api.ping()
                if (api.session().setup) return@work fail("This server has no accounts yet. Open it in a browser to create the admin account.")
            } catch (e: ShelfError.Offline) {
                return@work fail("Couldn’t reach ${shown(url)}. Check the server is running and this phone is on the same network.")
            } catch (e: ShelfError) {
                return@work fail("${shown(url)} answered, but it isn’t a Shelf server.")
            }
            if (store.server != url) store.signOut()
            store.server = url
            _state.update { it.copy(step = Step.SignIn, address = shown(url)) }
        }
    }

    fun signIn(username: String, password: String) {
        val server = store.server ?: return changeServer()
        if (username.isBlank() || password.isEmpty()) return fail("Enter your username and password.")
        _state.update { it.copy(error = null) }
        work {
            try {
                val (token, user) = apiFor(server).login(username.trim(), password)
                store.token = token
                store.username = user.username
                store.native = true
                _state.update { it.copy(step = Step.Done, note = null) }
            } catch (e: ShelfError.SignedOut) {
                fail("Wrong username or password.")
            } catch (e: ShelfError.Offline) {
                fail("Couldn’t reach ${shown(server)}. Check the server is running and this phone is on the same network.")
            } catch (e: ShelfError) {
                fail(e.message ?: "Couldn’t sign in.")
            }
        }
    }

    fun changeServer() = _state.update { it.copy(step = Step.Server, error = null) }

    /** Signing out on purpose: forget the sign-in, keep the server. */
    fun signOut() {
        store.signOut()
        _state.update { it.copy(step = Step.SignIn, error = null) }
    }

    /** Signed out by the server while using the app: back to sign-in, same server. */
    fun signedOut() {
        store.signOut()
        _state.update { it.copy(step = Step.SignIn, error = "You’ve been signed out. Sign in again to carry on.") }
    }

    private fun fail(message: String) = _state.update { it.copy(busy = false, error = message) }

    private fun work(block: suspend () -> Unit) {
        _state.update { it.copy(busy = true) }
        viewModelScope.launch {
            try { block() } finally { _state.update { it.copy(busy = false) } }
        }
    }
}
