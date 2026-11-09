package app.shelf.ui.common

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import app.shelf.data.ShelfError
import app.shelf.ui.SignedOutHandler
import app.shelf.ui.theme.Shelf
import kotlin.coroutines.cancellation.CancellationException

/** Something a screen is loading: still loading, here, or failed (and why). */
sealed interface Load<out T> {
    data object Loading : Load<Nothing>
    data class Ready<T>(val value: T) : Load<T>
    data class Failed(val error: ShelfError) : Load<Nothing>
}

/** Load something for a screen (again when `keys` change). Returns the state and a retry. */
@Composable
fun <T> rememberLoad(vararg keys: Any?, loader: suspend () -> T): Pair<Load<T>, () -> Unit> {
    var attempt by remember(*keys) { mutableIntStateOf(0) }
    val state by produceState<Load<T>>(Load.Loading, *keys, attempt) {
        value = Load.Loading
        value = try {
            Load.Ready(loader())
        } catch (e: CancellationException) {
            throw e
        } catch (e: ShelfError) {
            Load.Failed(e)
        } catch (e: Exception) {
            Load.Failed(ShelfError.Server(0, "Something went wrong reading the server’s answer."))
        }
    }
    return state to { attempt++ }
}

/** The screen's content when it's here; a spinner while loading; what went wrong and "Try again" if not. */
@Composable
fun <T> LoadContent(state: Load<T>, onRetry: () -> Unit, signedOut: SignedOutHandler, content: @Composable (T) -> Unit) {
    when (state) {
        is Load.Ready -> content(state.value)
        Load.Loading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            CircularProgressIndicator(color = Shelf.colors.cobalt, strokeWidth = 3.dp)
        }
        is Load.Failed -> {
            if (state.error is ShelfError.SignedOut) LaunchedEffect(Unit) { signedOut.signedOut() }
            val message = when (val e = state.error) {
                is ShelfError.Offline -> "Couldn’t reach the server. Check it’s running and that this phone is on the same network."
                is ShelfError.Server -> e.message ?: "The server couldn’t do that."
                else -> e.message ?: "Something went wrong."
            }
            Box(Modifier.fillMaxSize().padding(32.dp), contentAlignment = Alignment.Center) {
                Column(Modifier.widthIn(max = 360.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(14.dp)) {
                    Text("Can’t load this", style = MaterialTheme.typography.headlineSmall, color = Shelf.colors.ink)
                    Text(message, style = MaterialTheme.typography.bodyMedium, color = Shelf.colors.ink2, textAlign = TextAlign.Center)
                    OutlinedButton(onClick = onRetry) { Text("Try again", color = Shelf.colors.ink) }
                }
            }
        }
    }
}
