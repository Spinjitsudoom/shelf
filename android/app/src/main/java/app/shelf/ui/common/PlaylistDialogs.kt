package app.shelf.ui.common

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.shelf.R
import app.shelf.data.PlaylistSummary
import app.shelf.ui.covers.albumColor
import app.shelf.ui.theme.Shelf

/** Ask for a name (a new playlist, or renaming one). */
@Composable
fun NameDialog(title: String, initial: String, confirm: String, onDone: (String) -> Unit, onDismiss: () -> Unit, description: String? = null,
               onDescription: ((String) -> Unit)? = null) {
    var name by remember { mutableStateOf(initial) }
    var desc by remember { mutableStateOf(description ?: "") }
    AlertDialog(
        onDismissRequest = onDismiss, containerColor = Shelf.colors.sleeve,
        title = { Text(title, color = Shelf.colors.ink) },
        text = {
            Column {
                OutlinedTextField(name, { name = it }, label = { Text("Name") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                if (onDescription != null) {
                    Spacer(Modifier.height(10.dp))
                    OutlinedTextField(desc, { desc = it }, label = { Text("Description") }, modifier = Modifier.fillMaxWidth())
                }
            }
        },
        confirmButton = { TextButton(onClick = { if (name.isNotBlank()) { onDone(name.trim()); onDescription?.invoke(desc.trim()); onDismiss() } }) { Text(confirm, color = Shelf.colors.cobalt) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel", color = Shelf.colors.ink2) } },
    )
}

/** Are you sure? (deleting a playlist) */
@Composable
fun ConfirmDialog(title: String, text: String, confirm: String, onConfirm: () -> Unit, onDismiss: () -> Unit) {
    AlertDialog(onDismissRequest = onDismiss, containerColor = Shelf.colors.sleeve,
        title = { Text(title, color = Shelf.colors.ink) }, text = { Text(text, color = Shelf.colors.ink2) },
        confirmButton = { TextButton(onClick = { onConfirm(); onDismiss() }) { Text(confirm, color = Color(0xffff8a80)) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel", color = Shelf.colors.ink2) } })
}

/** Add a song to a playlist: the playlists you can add to, or a new one. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AddToPlaylistSheet(playlists: List<PlaylistSummary>?, coverUrl: (PlaylistSummary) -> List<String>, onPick: (PlaylistSummary) -> Unit,
                       onNew: (String) -> Unit, onDismiss: () -> Unit) {
    var naming by remember { mutableStateOf(false) }
    ModalBottomSheet(onDismissRequest = onDismiss, containerColor = Shelf.colors.sleeve) {
        Column(Modifier.navigationBarsPadding().padding(bottom = 10.dp)) {
            Text("Add to playlist", style = MaterialTheme.typography.headlineSmall, color = Shelf.colors.ink, modifier = Modifier.padding(horizontal = 20.dp, vertical = 6.dp))
            Row(Modifier.fillMaxWidth().clickable { naming = true }.padding(horizontal = 20.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(48.dp), contentAlignment = Alignment.Center) { Icon(painterResource(R.drawable.ic_plus), null, tint = Shelf.colors.ink) }
                Spacer(Modifier.width(14.dp))
                Text("New playlist", style = MaterialTheme.typography.titleMedium, color = Shelf.colors.ink)
            }
            LazyColumn(Modifier.heightIn(max = 420.dp)) {
                items(playlists.orEmpty().filter { it.canEdit }) { p ->
                    Row(Modifier.fillMaxWidth().clickable { onPick(p); onDismiss() }.padding(horizontal = 20.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                        MosaicCover(coverUrl(p), p.name, albumColor(null, p.name), Modifier.size(48.dp))
                        Spacer(Modifier.width(14.dp))
                        Column(Modifier.weight(1f)) {
                            Text(p.name, style = MaterialTheme.typography.titleMedium, color = Shelf.colors.ink, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            Text(plural(p.trackCount, "song"), style = MaterialTheme.typography.bodySmall, color = Shelf.colors.ink2)
                        }
                    }
                }
            }
        }
    }
    if (naming) NameDialog("New playlist", "", "Create", { onNew(it); onDismiss() }, { naming = false })
}
