package app.shelf.ui.player

import android.provider.Settings
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.shelf.R
import app.shelf.data.LibrarySource
import app.shelf.data.Track
import app.shelf.playback.PlayerConnection
import app.shelf.playback.PlayerUi
import app.shelf.ui.common.ArtistLinks
import app.shelf.ui.common.fmtTime
import app.shelf.ui.covers.CaseCover
import app.shelf.ui.covers.albumColor
import app.shelf.ui.covers.fallbackColor
import app.shelf.ui.theme.Shelf
import androidx.media3.common.Player

/** Now Playing: the album's colour behind it, the case with its CD turning, and every control. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun NowPlayingScreen(state: PlayerUi, source: LibrarySource, player: PlayerConnection, onArtist: (String) -> Unit, onContext: (String) -> Unit, onClose: () -> Unit,
                     liked: Boolean = false, onLike: () -> Unit = {}, lyrics: (suspend (Int) -> app.shelf.data.Lyrics)? = null) {
    val t = state.current ?: return onClose()
    // The album's own colour (the song doesn't carry it), fetched once per album.
    val color by produceState(fallbackColor(t.album), t.albumId) {
        value = runCatching { source.album(t.albumId) }.getOrNull()?.let { albumColor(it.color, it.title) } ?: fallbackColor(t.album)
    }
    var queueOpen by remember { mutableStateOf(false) }
    var showLyrics by androidx.compose.runtime.saveable.rememberSaveable { mutableStateOf(false) }
    val cover = { tr: Track -> source.coverUrl(tr.albumId, tr.cover, 640) }

    Column(Modifier.fillMaxSize().background(Brush.verticalGradient(listOf(color.copy(alpha = .85f), Shelf.colors.tray), endY = 2400f))
        .statusBarsPadding().navigationBarsPadding().padding(horizontal = 22.dp)) {
        Row(Modifier.fillMaxWidth().padding(top = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onClose) { Icon(painterResource(R.drawable.ic_back), "Close", tint = Shelf.colors.ink, modifier = Modifier.rotate(-90f)) }
            Column(Modifier.weight(1f).clickable(enabled = state.context != null) { state.context?.let { onContext(it.route) } },
                horizontalAlignment = Alignment.CenterHorizontally) {
                Text("Playing from", style = MaterialTheme.typography.labelSmall, color = Shelf.colors.ink2)
                Text(state.context?.label ?: t.album, style = MaterialTheme.typography.titleSmall, color = Shelf.colors.ink, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            if (lyrics != null) IconButton(onClick = { showLyrics = !showLyrics }) {
                Icon(painterResource(R.drawable.ic_mic), if (showLyrics) "Hide lyrics" else "Lyrics", tint = if (showLyrics) Shelf.colors.cobalt else Shelf.colors.ink)
            }
            IconButton(onClick = { queueOpen = true }) { Icon(painterResource(R.drawable.ic_queue), "Queue", tint = Shelf.colors.ink) }
        }
        Spacer(Modifier.height(18.dp))
        if (showLyrics && lyrics != null) LyricsPanel(t.id, state.positionMs, lyrics, player::seekTo, Modifier.fillMaxWidth().aspectRatio(1f))
        else SwipeToSkip(
            previous = state.previous?.let { p -> { CaseWithDisc(p, cover(p), false) } },
            current = { CaseWithDisc(t, cover(t), state.playing) },
            next = state.next?.let { n -> { CaseWithDisc(n, cover(n), false) } },
            onPrevious = player::previous, onNext = player::next,
            modifier = Modifier.fillMaxWidth().aspectRatio(1f),
        )
        Spacer(Modifier.weight(1f))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(t.title, style = MaterialTheme.typography.headlineSmall, color = Shelf.colors.ink, maxLines = 2, overflow = TextOverflow.Ellipsis)
                ArtistLinks(t.artist, t.artists, onArtist, style = MaterialTheme.typography.bodyLarge)
            }
            IconButton(onClick = onLike) {
                Icon(painterResource(if (liked) R.drawable.ic_heart_filled else R.drawable.ic_heart),
                    if (liked) "Remove from Favourites" else "Add to Favourites", tint = if (liked) Shelf.colors.cobalt else Shelf.colors.ink2)
            }
        }
        Spacer(Modifier.height(12.dp))
        Scrubber(state, player)
        Row(Modifier.fillMaxWidth().padding(vertical = 10.dp), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = player::toggleShuffle) {
                Icon(painterResource(R.drawable.ic_shuffle), "Shuffle", tint = if (state.shuffle) Shelf.colors.cobalt else Shelf.colors.ink2)
            }
            IconButton(onClick = player::previous, modifier = Modifier.size(56.dp)) { Icon(painterResource(R.drawable.ic_prev), "Previous", tint = Shelf.colors.ink, modifier = Modifier.size(32.dp)) }
            FilledIconButton(onClick = player::toggle, modifier = Modifier.size(76.dp), shape = CircleShape,
                colors = IconButtonDefaults.filledIconButtonColors(containerColor = Shelf.colors.ink, contentColor = Shelf.colors.tray)) {
                Icon(painterResource(if (state.playing) R.drawable.ic_pause else R.drawable.ic_play), if (state.playing) "Pause" else "Play", Modifier.size(34.dp))
            }
            IconButton(onClick = player::next, modifier = Modifier.size(56.dp)) { Icon(painterResource(R.drawable.ic_next), "Next", tint = Shelf.colors.ink, modifier = Modifier.size(32.dp)) }
            IconButton(onClick = player::cycleRepeat) {
                Box(contentAlignment = Alignment.Center) {
                    Icon(painterResource(R.drawable.ic_repeat), "Repeat", tint = if (state.repeat != Player.REPEAT_MODE_OFF) Shelf.colors.cobalt else Shelf.colors.ink2)
                    if (state.repeat == Player.REPEAT_MODE_ONE) Text("1", style = MaterialTheme.typography.labelSmall, color = Shelf.colors.cobalt)
                }
            }
        }
        Spacer(Modifier.height(10.dp))
    }

    if (queueOpen) {
        ModalBottomSheet(onDismissRequest = { queueOpen = false }, containerColor = Shelf.colors.sleeve) {
            Text("Queue", style = MaterialTheme.typography.headlineSmall, color = Shelf.colors.ink, modifier = Modifier.padding(horizontal = 20.dp, vertical = 6.dp))
            val list = rememberLazyListState(initialFirstVisibleItemIndex = state.index.coerceAtLeast(0))
            LazyColumn(state = list, modifier = Modifier.fillMaxWidth().height(480.dp)) {
                itemsIndexed(state.queue) { i, q ->
                    val now = i == state.index
                    Row(Modifier.fillMaxWidth().clickable { player.skipTo(i) }.padding(horizontal = 20.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                        CaseCover(source.coverUrl(q.albumId, q.cover, 160), q.album, fallbackColor(q.album), Modifier.size(44.dp))
                        Spacer(Modifier.size(12.dp))
                        Column(Modifier.weight(1f)) {
                            Text(q.title, style = MaterialTheme.typography.titleSmall, color = if (now) Shelf.colors.cobalt else Shelf.colors.ink, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            Text(q.artist, style = MaterialTheme.typography.bodySmall, color = Shelf.colors.ink2, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        }
                        Text(fmtTime(q.duration), style = MaterialTheme.typography.bodySmall, color = Shelf.colors.ink2)
                    }
                }
            }
        }
    }
}

@Composable
private fun Scrubber(state: PlayerUi, player: PlayerConnection) {
    var dragging by remember { mutableStateOf<Float?>(null) }
    val dur = state.durationMs.coerceAtLeast(1)
    val value = dragging ?: (state.positionMs.toFloat() / dur).coerceIn(0f, 1f)
    Slider(value = value, onValueChange = { dragging = it }, onValueChangeFinished = { dragging?.let { player.seekTo((it * dur).toLong()) }; dragging = null },
        colors = SliderDefaults.colors(thumbColor = Shelf.colors.ink, activeTrackColor = Shelf.colors.ink, inactiveTrackColor = Shelf.colors.ink.copy(alpha = .22f)))
    Row(Modifier.fillMaxWidth()) {
        Text(fmtTime(value * dur / 1000.0), style = MaterialTheme.typography.labelSmall, color = Shelf.colors.ink2)
        Spacer(Modifier.weight(1f))
        Text(fmtTime(dur / 1000.0), style = MaterialTheme.typography.labelSmall, color = Shelf.colors.ink2)
    }
}

/** The jewel case, with its CD half out to the right, turning while the music plays (unless the phone asks for less motion). */
@Composable
private fun CaseWithDisc(t: Track, url: String?, spinning: Boolean) {
    val reduceMotion = Settings.Global.getFloat(LocalContext.current.contentResolver, Settings.Global.ANIMATOR_DURATION_SCALE, 1f) == 0f
    val angle by if (spinning && !reduceMotion) rememberInfiniteTransition(label = "disc")
        .animateFloat(0f, 360f, infiniteRepeatable(tween(7000, easing = LinearEasing), RepeatMode.Restart), label = "spin")
    else remember { mutableStateOf(0f) }
    BoxWithConstraints(Modifier.fillMaxSize(), contentAlignment = Alignment.CenterStart) {
        val case = maxWidth * 0.86f
        Canvas(Modifier.size(case * 0.94f).offset(x = maxWidth - case * 0.94f, y = case * 0.03f).rotate(angle)) {
            val r = size.minDimension / 2
            drawCircle(Brush.sweepGradient(listOf(Color(0xffd9dde4), Color(0xfff2f4f8), Color(0xffbfc6d2), Color(0xffe9ecf1), Color(0xffcfd5de), Color(0xffd9dde4))), r)
            for (k in 1..6) drawCircle(Color.Black.copy(alpha = .05f), r * (0.38f + k * 0.09f), style = Stroke(1f))
            drawCircle(Color(0xff9aa2b0), r * 0.18f)
            drawCircle(Color(0xffe6e9ef), r * 0.07f)
            drawCircle(Color.White.copy(alpha = .35f), r * 0.98f, Offset(center.x, center.y), style = Stroke(2f))
        }
        CaseCover(url, t.album, fallbackColor(t.album), Modifier.size(case))
    }
}
