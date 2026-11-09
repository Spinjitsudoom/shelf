package app.shelf.ui.common

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.compositionLocalOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.shelf.R
import app.shelf.data.Track
import app.shelf.ui.covers.CaseCover
import app.shelf.ui.covers.fallbackColor
import app.shelf.ui.theme.Shelf

/** What can be done with a song, from anywhere: lists open the song menu through this. */
class SongActions(
    val open: (track: Track, removeFromPlaylist: (() -> Unit)?) -> Unit,
)

val LocalSongActions = compositionLocalOf<SongActions?> { null }

/** One row in the song menu. */
data class MenuItem(val label: String, val icon: Int, val run: () -> Unit)

/** The song menu: the song at the top, then what can be done with it. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SongMenu(track: Track, coverUrl: String?, items: List<MenuItem>, onDismiss: () -> Unit) {
    ModalBottomSheet(onDismissRequest = onDismiss, containerColor = Shelf.colors.sleeve) {
        Column(Modifier.navigationBarsPadding().padding(bottom = 10.dp)) {
            Row(Modifier.padding(horizontal = 20.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                CaseCover(coverUrl, track.album, fallbackColor(track.album), Modifier.size(52.dp))
                Spacer(Modifier.width(14.dp))
                Column(Modifier.weight(1f)) {
                    Text(track.title, style = MaterialTheme.typography.titleMedium, color = Shelf.colors.ink, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    Text("${track.artist}, ${track.album}", style = MaterialTheme.typography.bodySmall, color = Shelf.colors.ink2, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
            HorizontalDivider(color = Shelf.colors.rule, modifier = Modifier.padding(vertical = 6.dp))
            items.forEach { item ->
                Row(Modifier.fillMaxWidth().clickable { onDismiss(); item.run() }.padding(horizontal = 20.dp, vertical = 13.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    Icon(painterResource(item.icon), null, tint = Shelf.colors.ink2, modifier = Modifier.size(22.dp))
                    Spacer(Modifier.width(18.dp))
                    Text(item.label, style = MaterialTheme.typography.bodyLarge, color = Shelf.colors.ink)
                }
            }
            Spacer(Modifier.height(4.dp))
        }
    }
}
