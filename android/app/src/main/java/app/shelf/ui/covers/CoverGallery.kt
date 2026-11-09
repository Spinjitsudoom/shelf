package app.shelf.ui.covers

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import app.shelf.ui.theme.Shelf

/** Every cover style side by side, for checking them by eye on a phone (temporary: Task 4 replaces it). */
@Composable
fun CoverGallery() {
    Column(Modifier.fillMaxSize().background(Shelf.colors.tray).statusBarsPadding().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Text("Shelf Preview", style = MaterialTheme.typography.displayMedium, color = Shelf.colors.ink)
        Row(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
            CaseCover(null, "The Black Album", albumColor(null, "The Black Album"), Modifier.size(160.dp))
            CaseCover(null, "Master Of Puppets", albumColor("#8a3b2a", "Master Of Puppets"), Modifier.size(160.dp), vinyl = true)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
            TapeCover("Shelf Mix 1", Color(0xffe8590c), emptyList(), Modifier.size(160.dp), rolling = true)
            TapeCover("Smoke On The Water - Live on the BBC Friday Rock Show Radio", Color(0xff364fc7), emptyList(), Modifier.size(160.dp))
        }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            CaseCover(null, "Small", albumColor(null, "Small"), Modifier.size(48.dp))
            Text("Abbey Road", style = MaterialTheme.typography.titleMedium, color = Shelf.colors.ink)
            Text("Måneskin, 日本語", style = MaterialTheme.typography.bodyMedium, color = Shelf.colors.ink2)
        }
    }
}
