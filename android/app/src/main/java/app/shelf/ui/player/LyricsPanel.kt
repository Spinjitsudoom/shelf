package app.shelf.ui.player

import androidx.compose.animation.animateColorAsState
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import app.shelf.data.Lyrics
import app.shelf.ui.theme.Shelf

/** A song's lyrics in place of the cover: timed lines follow the song (tap one to go there), plain lyrics scroll. */
@Composable
fun LyricsPanel(trackId: Int, positionMs: Long, load: suspend (Int) -> Lyrics, onSeek: (Long) -> Unit, modifier: Modifier = Modifier) {
    val lyrics by produceState<Result<Lyrics>?>(null, trackId) { value = runCatching { load(trackId) } }
    Box(modifier, contentAlignment = Alignment.Center) {
        val l = lyrics
        when {
            l == null -> CircularProgressIndicator(color = Shelf.colors.ink2)
            l.isFailure -> Note("Couldn’t load the lyrics. Check the connection and try again.")
            else -> {
                val ly = l.getOrThrow()
                when {
                    ly.kind == "synced" && ly.lines.isNotEmpty() -> Synced(ly, positionMs, onSeek)
                    ly.kind == "plain" && !ly.text.isNullOrBlank() ->
                        Text(ly.text, style = MaterialTheme.typography.titleMedium, color = Shelf.colors.ink,
                            modifier = Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(vertical = 12.dp))
                    ly.kind == "instrumental" -> Note("Instrumental")
                    else -> Note("No lyrics for this song")
                }
            }
        }
    }
}

@Composable
private fun Synced(ly: Lyrics, positionMs: Long, onSeek: (Long) -> Unit) {
    val active = activeLine(ly.lines, positionMs / 1000.0)
    val list = rememberLazyListState()
    // Keep the current line a little below the top, unless the person is scrolling themselves.
    LaunchedEffect(active) { if (active >= 0 && !list.isScrollInProgress) list.animateScrollToItem((active - 2).coerceAtLeast(0)) }
    LazyColumn(state = list, modifier = Modifier.fillMaxWidth(), contentPadding = PaddingValues(vertical = 24.dp)) {
        itemsIndexed(ly.lines) { i, line ->
            val color by animateColorAsState(when {
                i == active -> Shelf.colors.ink
                i < active -> Shelf.colors.ink2.copy(alpha = .55f)
                else -> Shelf.colors.ink2
            }, label = "line")
            Text(line.text.ifBlank { "♪" }, style = MaterialTheme.typography.headlineSmall.copy(fontWeight = if (i == active) FontWeight.Bold else FontWeight.SemiBold),
                color = color, modifier = Modifier.fillMaxWidth().clickable { onSeek((line.t * 1000).toLong()) }.padding(vertical = 7.dp))
        }
    }
}

@Composable
private fun Note(text: String) = Text(text, style = MaterialTheme.typography.titleMedium, color = Shelf.colors.ink2)
