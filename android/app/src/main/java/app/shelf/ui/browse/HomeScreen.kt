package app.shelf.ui.browse

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.shelf.data.Home
import app.shelf.data.LibrarySource
import app.shelf.data.MixSummary
import app.shelf.ui.SignedOutHandler
import app.shelf.ui.common.CoverCard
import app.shelf.ui.common.LoadContent
import app.shelf.ui.common.SectionTitle
import app.shelf.ui.common.Shelf
import app.shelf.ui.common.rememberLoad
import app.shelf.ui.covers.CaseCover
import app.shelf.ui.covers.TapeCover
import app.shelf.ui.covers.albumColor
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import java.time.LocalTime
import app.shelf.ui.theme.Shelf as Theme

private data class HomeData(val home: Home, val mixes: List<MixSummary>)

private fun greeting(name: String?): String {
    val h = LocalTime.now().hour
    val part = when { h < 5 -> "Good night"; h < 12 -> "Good morning"; h < 18 -> "Good afternoon"; else -> "Good evening" }
    return name?.let { "$part, ${it.substringBefore(' ')}" } ?: part
}

@Composable
fun HomeScreen(source: LibrarySource, username: String?, onAlbum: (Int) -> Unit, onMix: (String) -> Unit, onPlayAlbum: (Int) -> Unit, signedOut: SignedOutHandler,
               onSettings: () -> Unit = {}, onPeople: (() -> Unit)? = null) {
    val (state, retry) = rememberLoad("home") {
        coroutineScope { val h = async { source.home() }; val m = async { source.mixes() }; HomeData(h.await(), m.await()) }
    }
    LoadContent(state, retry, signedOut) { d ->
        LazyColumn(Modifier.fillMaxSize()) {
            item {
                Row(Modifier.statusBarsPadding().padding(start = 16.dp, end = 4.dp, top = 18.dp, bottom = 6.dp), verticalAlignment = Alignment.Top) {
                    Column(Modifier.weight(1f)) {
                        Text("Home", style = MaterialTheme.typography.displayMedium, color = Theme.colors.ink)
                        Text(greeting(username), style = MaterialTheme.typography.bodyLarge, color = Theme.colors.ink2)
                    }
                    if (onPeople != null) androidx.compose.material3.IconButton(onClick = onPeople) {
                        androidx.compose.material3.Icon(androidx.compose.ui.res.painterResource(app.shelf.R.drawable.ic_artists), "People", tint = Theme.colors.ink)
                    }
                    androidx.compose.material3.IconButton(onClick = onSettings) {
                        androidx.compose.material3.Icon(androidx.compose.ui.res.painterResource(app.shelf.R.drawable.ic_settings), "Settings", tint = Theme.colors.ink)
                    }
                }
            }
            d.home.recent.firstOrNull()?.let { a ->
                item {
                    SectionTitle("Jump back in")
                    Surface(onClick = { onAlbum(a.id) }, color = Theme.colors.sleeve, shape = RoundedCornerShape(12.dp),
                        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp)) {
                        Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                            CaseCover(source.coverUrl(a.id, a.cover, 320), a.title, albumColor(a.color, a.title), Modifier.size(84.dp))
                            Spacer(Modifier.width(14.dp))
                            Column(Modifier.weight(1f)) {
                                Text(a.title, style = MaterialTheme.typography.titleLarge, color = Theme.colors.ink, maxLines = 2, overflow = TextOverflow.Ellipsis)
                                Text(a.artist, style = MaterialTheme.typography.bodyMedium, color = Theme.colors.ink2, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            }
                        }
                    }
                }
            }
            if (d.mixes.isNotEmpty()) item {
                SectionTitle("Made for you")
                Shelf(d.mixes) { m ->
                    CoverCard(m.name, m.description, onClick = { onMix(m.key) }) {
                        TapeCover(m.name, albumColor(m.color, m.name), m.covers.mapNotNull { source.coverUrl(it.albumId, it.cover, 160) })
                    }
                }
            }
            listOf("Recently added" to d.home.added, "Rediscover" to d.home.rediscover).forEach { (title, albums) ->
                if (albums.isNotEmpty()) item {
                    SectionTitle(title)
                    Shelf(albums) { a ->
                        CoverCard(a.title, a.artist, onClick = { onAlbum(a.id) }) {
                            CaseCover(source.coverUrl(a.id, a.cover, 320), a.title, albumColor(a.color, a.title))
                        }
                    }
                }
            }
            item { Spacer(Modifier.height(24.dp)) }
        }
    }
}
