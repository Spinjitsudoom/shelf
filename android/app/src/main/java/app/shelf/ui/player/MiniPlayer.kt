package app.shelf.ui.player

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.shelf.R
import app.shelf.data.Track
import app.shelf.playback.PlayerUi
import app.shelf.ui.covers.CaseCover
import app.shelf.ui.covers.fallbackColor
import app.shelf.ui.theme.Shelf

/** The song playing, above the bottom bar: swipe it to skip, tap it for Now Playing. */
@Composable
fun MiniPlayer(state: PlayerUi, coverUrl: (Track) -> String?, onToggle: () -> Unit, onNext: () -> Unit, onPrevious: () -> Unit, onOpen: () -> Unit) {
    val t = state.current ?: return
    val shape = RoundedCornerShape(10.dp)
    Box(Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 6.dp).clip(shape).background(Shelf.colors.sleeve)
        .clickable(onClick = onOpen).testTag("mini-player")) {
        Row(Modifier.fillMaxWidth().height(60.dp).padding(start = 8.dp, end = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            SwipeToSkip(
                previous = state.previous?.let { p -> { SongLine(p, coverUrl) } },
                current = { SongLine(t, coverUrl, titleTag = "mini-title") },
                next = state.next?.let { n -> { SongLine(n, coverUrl) } },
                onPrevious = onPrevious, onNext = onNext,
                modifier = Modifier.weight(1f).fillMaxHeight(),
            )
            IconButton(onClick = onToggle) {
                Icon(painterResource(if (state.playing) R.drawable.ic_pause else R.drawable.ic_play),
                    contentDescription = if (state.playing) "Pause" else "Play", tint = Shelf.colors.ink)
            }
        }
        // how far into the song
        val p = if (state.durationMs > 0) (state.positionMs.toFloat() / state.durationMs).coerceIn(0f, 1f) else 0f
        Box(Modifier.align(Alignment.BottomStart).fillMaxWidth().height(2.dp).background(Shelf.colors.rule))
        Box(Modifier.align(Alignment.BottomStart).fillMaxWidth(p).height(2.dp).background(Shelf.colors.ink))
    }
}

@Composable
private fun SongLine(t: Track, coverUrl: (Track) -> String?, titleTag: String? = null) {
    Row(Modifier.fillMaxSize(), verticalAlignment = Alignment.CenterVertically) {
        CaseCover(coverUrl(t), t.album, fallbackColor(t.album), Modifier.size(44.dp))
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(t.title, style = MaterialTheme.typography.titleSmall, color = Shelf.colors.ink, maxLines = 1, overflow = TextOverflow.Ellipsis,
                modifier = if (titleTag != null) Modifier.testTag(titleTag) else Modifier)
            Text(t.artist, style = MaterialTheme.typography.bodySmall, color = Shelf.colors.ink2, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
    }
}
