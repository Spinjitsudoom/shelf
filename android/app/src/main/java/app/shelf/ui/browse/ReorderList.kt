package app.shelf.ui.browse

import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.zIndex
import app.shelf.R
import app.shelf.data.Track
import app.shelf.data.moveItem
import app.shelf.ui.theme.Shelf

/** Put a playlist's songs in order: drag a song by its handle; Done saves the new order. */
@Composable
fun ReorderList(title: String, tracks: List<Track>, onDone: (List<Track>) -> Unit, onCancel: () -> Unit) {
    var items by remember { mutableStateOf(tracks) }
    var dragging by remember { mutableStateOf<Int?>(null) }
    var offset by remember { mutableFloatStateOf(0f) }
    val list = rememberLazyListState()
    val haptics = LocalHapticFeedback.current
    Column(Modifier.fillMaxSize().background(Shelf.colors.tray)) {
        Row(Modifier.statusBarsPadding().padding(start = 16.dp, end = 8.dp, top = 10.dp, bottom = 6.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Reorder", style = MaterialTheme.typography.labelMedium, color = Shelf.colors.ink2)
                Text(title, style = MaterialTheme.typography.headlineSmall, color = Shelf.colors.ink, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            TextButton(onClick = onCancel) { Text("Cancel", color = Shelf.colors.ink2) }
            TextButton(onClick = { onDone(items) }) { Text("Done", color = Shelf.colors.cobalt) }
        }
        LazyColumn(state = list, modifier = Modifier.fillMaxSize()) {
            itemsIndexed(items, key = { _, t -> t.entryId ?: t.id }) { i, t ->
                val lifted = dragging == i
                Row(Modifier.zIndex(if (lifted) 1f else 0f).graphicsLayer { translationY = if (lifted) offset else 0f; shadowElevation = if (lifted) 12f else 0f }
                    .background(if (lifted) Shelf.colors.sleeve else Shelf.colors.tray).fillMaxWidth().padding(start = 16.dp, end = 4.dp, top = 6.dp, bottom = 6.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(t.title, style = MaterialTheme.typography.titleMedium, color = Shelf.colors.ink, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text(t.artist, style = MaterialTheme.typography.bodySmall, color = Shelf.colors.ink2, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    }
                    Spacer(Modifier.width(8.dp))
                    Icon(painterResource(R.drawable.ic_sort), contentDescription = "Drag to move ${t.title}", tint = Shelf.colors.ink2,
                        modifier = Modifier.size(48.dp).padding(12.dp).pointerInput(t.entryId ?: t.id) {
                            detectDragGestures(
                                onDragStart = { dragging = items.indexOf(t); offset = 0f; haptics.performHapticFeedback(HapticFeedbackType.LongPress) },
                                onDrag = { change, d ->
                                    change.consume()
                                    val cur = dragging ?: return@detectDragGestures
                                    offset += d.y
                                    val h = list.layoutInfo.visibleItemsInfo.firstOrNull { it.index == cur }?.size?.toFloat() ?: return@detectDragGestures
                                    if (offset > h / 2 && cur < items.lastIndex) { items = moveItem(items, cur, cur + 1); dragging = cur + 1; offset -= h }
                                    else if (offset < -h / 2 && cur > 0) { items = moveItem(items, cur, cur - 1); dragging = cur - 1; offset += h }
                                },
                                onDragEnd = { dragging = null; offset = 0f },
                                onDragCancel = { dragging = null; offset = 0f },
                            )
                        })
                }
            }
        }
    }
}
