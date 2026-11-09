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
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.dp
import app.shelf.R
import app.shelf.data.LibrarySource
import app.shelf.playback.PlayContext
import app.shelf.ui.SignedOutHandler
import app.shelf.ui.Routes
import app.shelf.ui.common.CoverCard
import app.shelf.ui.common.LoadContent
import app.shelf.ui.common.SectionTitle
import app.shelf.ui.common.Shelf
import app.shelf.ui.common.TrackRow
import app.shelf.ui.common.fmtTime
import app.shelf.ui.common.heroBrush
import app.shelf.ui.common.plural
import app.shelf.ui.common.rememberLoad
import app.shelf.ui.covers.CaseCover
import app.shelf.ui.covers.albumColor
import app.shelf.ui.theme.ArchivoDisplay
import app.shelf.ui.theme.Shelf as Theme

@Composable
fun ArtistScreen(name: String, source: LibrarySource, onPlay: OnPlay, onAlbum: (Int) -> Unit, onBack: () -> Unit, signedOut: SignedOutHandler,
                 onRadio: (() -> Unit)? = null) {
    val (state, retry) = rememberLoad(name) { source.artist(name) }
    LoadContent(state, retry, signedOut) { a ->
        val color = a.albums.firstOrNull()?.let { albumColor(it.color, it.title) } ?: albumColor(null, a.name)
        val ctx = PlayContext(a.name, Routes.artist(a.name))
        val popular = a.popular.take(5)
        Box(Modifier.fillMaxSize()) {
            LazyColumn(Modifier.fillMaxSize()) {
                item {
                    Column(Modifier.fillMaxWidth().background(heroBrush(color, Theme.colors.tray)).statusBarsPadding().padding(start = 20.dp, end = 20.dp, top = 96.dp, bottom = 16.dp)) {
                        Text(a.name, style = pageTitleStyle(a.name).copy(fontFamily = ArchivoDisplay), color = Theme.colors.ink)
                        Text(listOf(plural(a.albums.size, "release"), plural(a.popular.size.coerceAtLeast(popular.size), "popular song")).joinToString(", "),
                            style = MaterialTheme.typography.bodyMedium, color = Theme.colors.ink2)
                        Spacer(Modifier.height(16.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                            Button(onClick = { if (a.popular.isNotEmpty()) onPlay(a.popular, 0, ctx) }, enabled = a.popular.isNotEmpty(),
                                colors = ButtonDefaults.buttonColors(containerColor = Theme.colors.cobalt, contentColor = Theme.colors.cobaltInk)) {
                                Icon(painterResource(R.drawable.ic_play), null, Modifier.size(20.dp)); Spacer(Modifier.size(8.dp)); Text("Play")
                            }
                            if (onRadio != null) androidx.compose.material3.OutlinedButton(onClick = onRadio) {
                                Icon(painterResource(R.drawable.ic_radio), null, Modifier.size(20.dp), tint = Theme.colors.ink); Spacer(Modifier.size(8.dp)); Text("Radio", color = Theme.colors.ink)
                            }
                        }
                    }
                }
                if (popular.isNotEmpty()) item { SectionTitle("Popular") }
                itemsIndexed(popular) { i, t ->
                    TrackRow(null, t.title, t.album, fmtTime(t.duration), { onPlay(popular, i, ctx) },
                        coverUrl = source.coverUrl(t.albumId, t.cover, 160), coverColor = albumColor(null, t.album), track = t)
                }
                if (a.albums.isNotEmpty()) item {
                    SectionTitle("Releases")
                    Shelf(a.albums) { al ->
                        CoverCard(al.title, al.year?.toString(), onClick = { onAlbum(al.id) }) {
                            CaseCover(source.coverUrl(al.id, al.cover, 320), al.title, albumColor(al.color, al.title))
                        }
                    }
                }
                if (a.appearsOn.isNotEmpty()) item {
                    SectionTitle("Appears on")
                    Shelf(a.appearsOn) { al ->
                        CoverCard(al.title, al.artist, onClick = { onAlbum(al.id) }) {
                            CaseCover(source.coverUrl(al.id, al.cover, 320), al.title, albumColor(al.color, al.title))
                        }
                    }
                }
                item { Spacer(Modifier.height(24.dp)) }
            }
            IconButton(onClick = onBack, modifier = Modifier.statusBarsPadding().padding(4.dp)) {
                Icon(painterResource(R.drawable.ic_back), contentDescription = "Back", tint = Theme.colors.ink)
            }
        }
    }
}
