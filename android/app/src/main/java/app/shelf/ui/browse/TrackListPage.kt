package app.shelf.ui.browse

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedIconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.shelf.R
import app.shelf.data.Track
import app.shelf.ui.common.TrackRow
import app.shelf.ui.common.fmtTime
import app.shelf.ui.common.heroBrush
import app.shelf.ui.theme.ArchivoDisplay
import app.shelf.ui.theme.Shelf

/** A page's title, smaller as it gets longer (like the web's titleFit), so long titles stay readable. */
@Composable
fun pageTitleStyle(title: String): TextStyle {
    val base = MaterialTheme.typography.displayMedium
    return when {
        title.length > 64 -> base.copy(fontSize = 21.sp, lineHeight = 23.sp)
        title.length > 38 -> base.copy(fontSize = 25.sp, lineHeight = 27.sp)
        title.length > 22 -> base.copy(fontSize = 30.sp, lineHeight = 32.sp)
        else -> base
    }
}

/**
 * An album, playlist, mix or Favourites: a header tinted with its colour (cover, kind, title,
 * who it's by, facts, Play and Shuffle), then its songs. Tapping a song plays from it.
 */
@Composable
fun TrackListPage(
    color: Color, kind: String?, title: String, cover: @Composable () -> Unit, byline: (@Composable () -> Unit)?, facts: String,
    tracks: List<Track>, numbered: Boolean, coverUrl: (Track) -> String?, onTrack: (Int) -> Unit, onShuffle: () -> Unit, onBack: () -> Unit,
    onRemove: ((Int) -> Unit)? = null,
) {
    val discs = numbered && tracks.map { it.discNo ?: 1 }.distinct().size > 1
    Box(Modifier.fillMaxSize()) {
        LazyColumn(Modifier.fillMaxSize().testTag("tracks")) {
            item {
                Column(Modifier.fillMaxWidth().background(heroBrush(color, Shelf.colors.tray)).statusBarsPadding().padding(top = 52.dp, start = 20.dp, end = 20.dp, bottom = 14.dp)) {
                    Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) { Box(Modifier.size(232.dp)) { cover() } }
                    Spacer(Modifier.height(22.dp))
                    if (kind != null) Text(kind, style = MaterialTheme.typography.labelMedium, color = Shelf.colors.ink2)
                    Text(title, style = pageTitleStyle(title).copy(fontFamily = ArchivoDisplay), color = Shelf.colors.ink)
                    if (byline != null) { Spacer(Modifier.height(6.dp)); byline() }
                    Spacer(Modifier.height(4.dp))
                    Text(facts, style = MaterialTheme.typography.bodyMedium, color = Shelf.colors.ink2)
                    Spacer(Modifier.height(16.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.CenterVertically) {
                        Button(onClick = { if (tracks.isNotEmpty()) onTrack(0) }, enabled = tracks.isNotEmpty(),
                            colors = ButtonDefaults.buttonColors(containerColor = Shelf.colors.cobalt, contentColor = Shelf.colors.cobaltInk),
                            contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 22.dp, vertical = 12.dp)) {
                            Icon(painterResource(R.drawable.ic_play), null, Modifier.size(20.dp)); Spacer(Modifier.size(8.dp)); Text("Play", style = MaterialTheme.typography.labelLarge)
                        }
                        OutlinedIconButton(onClick = onShuffle, enabled = tracks.isNotEmpty()) {
                            Icon(painterResource(R.drawable.ic_shuffle), contentDescription = "Shuffle", tint = Shelf.colors.ink)
                        }
                    }
                }
            }
            if (tracks.isEmpty()) item {
                Text("No songs here yet.", style = MaterialTheme.typography.bodyMedium, color = Shelf.colors.ink2, modifier = Modifier.padding(20.dp))
            }
            itemsIndexed(tracks, key = { i, t -> "$i-${t.id}" }) { i, t ->
                if (discs && (i == 0 || (tracks[i - 1].discNo ?: 1) != (t.discNo ?: 1))) {
                    Text("Disc ${t.discNo ?: 1}", style = MaterialTheme.typography.labelLarge, color = Shelf.colors.ink2,
                        modifier = Modifier.padding(start = 16.dp, top = 14.dp, bottom = 4.dp))
                }
                TrackRow(
                    number = if (numbered) (t.trackNo ?: (i + 1)).toString() else null,
                    title = t.title,
                    subtitle = if (!numbered || t.artist != t.albumArtist) t.artist else null,
                    length = fmtTime(t.duration),
                    onClick = { onTrack(i) },
                    coverUrl = coverUrl(t),
                    coverColor = app.shelf.ui.covers.fallbackColor(t.album),
                    track = t, removeFromPlaylist = onRemove?.let { { it(i) } },
                )
            }
            item { Spacer(Modifier.height(24.dp)) }
        }
        IconButton(onClick = onBack, modifier = Modifier.statusBarsPadding().padding(4.dp)) {
            Icon(painterResource(R.drawable.ic_back), contentDescription = "Back", tint = Shelf.colors.ink)
        }
    }
}
