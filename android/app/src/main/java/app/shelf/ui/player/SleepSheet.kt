package app.shelf.ui.player

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import app.shelf.playback.SleepState
import app.shelf.playback.SleepTimer
import app.shelf.ui.theme.Shelf

/** How the sleep timer reads on its button: minutes left, or the end of the song. */
fun sleepLabel(s: SleepState?, now: Long = System.currentTimeMillis()): String = when {
    s == null -> "Sleep timer"
    s.endOfSong -> "Sleep timer: end of this song"
    else -> "Sleep timer: ${((s.endsAt!! - now) / 60_000.0).let { kotlin.math.ceil(it).toInt().coerceAtLeast(1) }} min left"
}

private fun label(minutes: Int) = when {
    minutes < 60 -> "$minutes minutes"
    minutes == 60 -> "1 hour"
    else -> "1 hour ${minutes - 60} minutes"
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SleepSheet(timer: SleepTimer, state: SleepState?, say: (String) -> Unit, onDismiss: () -> Unit) {
    ModalBottomSheet(onDismissRequest = onDismiss, containerColor = Shelf.colors.sleeve) {
        Column(Modifier.navigationBarsPadding().padding(bottom = 12.dp)) {
            Text(sleepLabel(state), style = MaterialTheme.typography.headlineSmall, color = Shelf.colors.ink, modifier = Modifier.padding(horizontal = 20.dp, vertical = 6.dp))
            @Composable fun row(text: String, run: () -> Unit) = Text(text, style = MaterialTheme.typography.bodyLarge, color = Shelf.colors.ink,
                modifier = Modifier.fillMaxWidth().clickable { run(); onDismiss() }.padding(horizontal = 20.dp, vertical = 13.dp))
            timer.choices.forEach { m -> row(label(m)) { timer.set(m); say("Sleep timer: $m min") } }
            row("End of this song") { timer.endOfSong(); say("Sleep timer: end of this song") }
            if (state != null) row("Turn off the sleep timer") { timer.cancel(); say("Sleep timer off") }
        }
    }
}
