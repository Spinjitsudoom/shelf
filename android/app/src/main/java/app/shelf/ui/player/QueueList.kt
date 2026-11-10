package app.shelf.ui.player

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
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
import app.shelf.ui.common.fmtTime
import app.shelf.ui.theme.Shelf

/**
 * The queue: tap a song to play it; drag a song still to come by its handle to change when it
 * plays. The playing song and the ones already played stay put. The move is made once, on
 * release. While shuffled (on this phone) the list isn't the playing order, so it can't be dragged.
 */
@Composable
fun QueueList(
    queue: List<Track>, index: Int, canReorder: Boolean,
    onPlay: (Int) -> Unit, onMove: (from: Int, to: Int) -> Unit,
    leading: @Composable (Track) -> Unit, modifier: Modifier = Modifier,
) {
    // Positions in the queue, in the order shown; differs from 0..n only mid-drag.
    var order by remember(queue, index) { mutableStateOf(queue.indices.toList()) }
    var dragging by remember(queue, index) { mutableStateOf<Int?>(null) } // the queue position being dragged
    var offset by remember { mutableFloatStateOf(0f) }
    val list = rememberLazyListState(initialFirstVisibleItemIndex = index.coerceAtLeast(0))
    val haptics = LocalHapticFeedback.current
    val header = if (canReorder) 0 else 1

    LazyColumn(state = list, modifier = modifier.fillMaxWidth()) {
        if (!canReorder) item {
            Text("Turn off shuffle to change the order", style = MaterialTheme.typography.bodySmall, color = Shelf.colors.ink2,
                modifier = Modifier.padding(horizontal = 20.dp, vertical = 4.dp))
        }
        itemsIndexed(order, key = { _, q -> q }) { _, q ->
            val t = queue[q]
            val lifted = dragging == q
            Row(
                Modifier.zIndex(if (lifted) 1f else 0f)
                    .graphicsLayer { translationY = if (lifted) offset else 0f; shadowElevation = if (lifted) 12f else 0f }
                    .background(if (lifted) Shelf.colors.tray else Shelf.colors.sleeve)
                    .fillMaxWidth().clickable { onPlay(q) }.padding(start = 20.dp, end = 8.dp, top = 10.dp, bottom = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                leading(t)
                Spacer(Modifier.size(12.dp))
                Column(Modifier.weight(1f)) {
                    Text(t.title, style = MaterialTheme.typography.titleSmall, color = if (q == index) Shelf.colors.cobalt else Shelf.colors.ink,
                        maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text(t.artist, style = MaterialTheme.typography.bodySmall, color = Shelf.colors.ink2, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
                Text(fmtTime(t.duration), style = MaterialTheme.typography.bodySmall, color = Shelf.colors.ink2)
                if (canReorder && q > index) {
                    Icon(painterResource(R.drawable.ic_sort), contentDescription = "Drag to move ${t.title}", tint = Shelf.colors.ink2,
                        modifier = Modifier.size(44.dp).padding(10.dp).pointerInput(q) {
                            detectDragGestures(
                                onDragStart = { dragging = q; offset = 0f; haptics.performHapticFeedback(HapticFeedbackType.LongPress) },
                                onDrag = { change, d ->
                                    change.consume()
                                    offset += d.y
                                    val at = order.indexOf(q)
                                    val h = list.layoutInfo.visibleItemsInfo.firstOrNull { it.index == at + header }?.size?.toFloat() ?: return@detectDragGestures
                                    if (offset > h / 2 && at < order.lastIndex) { order = moveItem(order, at, at + 1); offset -= h }
                                    else if (offset < -h / 2 && at > index + 1) { order = moveItem(order, at, at - 1); offset += h }
                                },
                                onDragEnd = {
                                    val to = order.indexOf(q)
                                    dragging = null; offset = 0f
                                    if (to != q) onMove(q, to)
                                },
                                onDragCancel = { dragging = null; offset = 0f; order = queue.indices.toList() },
                            )
                        })
                } else Spacer(Modifier.size(width = 44.dp, height = 1.dp))
            }
        }
    }
}
