package app.shelf.ui.player

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.shelf.R
import app.shelf.connect.ConnectUi
import app.shelf.ui.theme.Shelf

private val KINDS = mapOf("computer" to "Computer", "phone" to "Phone", "tablet" to "Tablet", "tv" to "TV", "speaker" to "Speaker")

/** Where the music plays: this phone first, then the user's other devices. Picking one moves the music there. */
@Composable
fun DeviceList(ui: ConnectUi, onPick: (String) -> Unit) {
    Column(Modifier.fillMaxWidth()) {
        Text("Play on", style = MaterialTheme.typography.headlineSmall, color = Shelf.colors.ink, modifier = Modifier.padding(horizontal = 20.dp, vertical = 6.dp))
        if (!ui.connected) {
            Text("Can’t reach the server to see your other devices", style = MaterialTheme.typography.bodyMedium, color = Shelf.colors.ink2,
                modifier = Modifier.padding(horizontal = 20.dp, vertical = 8.dp))
        }
        val others = ui.devices.filter { it.id != ui.selfId }
        val nobody = ui.activeId == null || ui.devices.none { it.id == ui.activeId }
        DeviceRow("This phone", null, ui.activeId == ui.selfId || nobody) { onPick(ui.selfId) }
        others.forEach { d -> DeviceRow(d.name.ifBlank { "Web browser" }, KINDS[d.kind] ?: "Computer", d.id == ui.activeId) { onPick(d.id) } }
        if (ui.connected && others.isEmpty()) {
            Text("Open Shelf on a computer, TV or another phone, signed in as you, and it shows up here.", style = MaterialTheme.typography.bodySmall,
                color = Shelf.colors.ink2, modifier = Modifier.padding(horizontal = 20.dp, vertical = 8.dp))
        }
    }
}

@Composable
private fun DeviceRow(name: String, kind: String?, active: Boolean, onClick: () -> Unit) {
    val color = if (active) Shelf.colors.cobalt else Shelf.colors.ink
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 20.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
        Icon(painterResource(R.drawable.ic_devices), null, tint = color, modifier = Modifier.size(24.dp))
        Spacer(Modifier.width(16.dp))
        Column(Modifier.weight(1f)) {
            Text(name, style = MaterialTheme.typography.titleMedium, color = color, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.testTag("device-name"))
            when {
                active -> Text("Playing", style = MaterialTheme.typography.bodySmall, color = Shelf.colors.cobalt)
                kind != null -> Text(kind, style = MaterialTheme.typography.bodySmall, color = Shelf.colors.ink2)
            }
        }
        if (active) Icon(painterResource(R.drawable.ic_check), "Playing here", tint = Shelf.colors.cobalt, modifier = Modifier.size(22.dp))
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DevicesSheet(ui: ConnectUi, onPick: (String) -> Unit, onDismiss: () -> Unit) {
    ModalBottomSheet(onDismissRequest = onDismiss, containerColor = Shelf.colors.sleeve) {
        Column(Modifier.navigationBarsPadding().padding(bottom = 12.dp)) { DeviceList(ui) { onPick(it); onDismiss() } }
    }
}
