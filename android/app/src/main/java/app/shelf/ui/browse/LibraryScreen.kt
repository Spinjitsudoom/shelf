package app.shelf.ui.browse

import androidx.compose.foundation.background
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.shelf.data.Album
import app.shelf.data.ArtistSummary
import app.shelf.data.LibrarySource
import app.shelf.data.PlaylistSummary
import app.shelf.ui.SignedOutHandler
import app.shelf.ui.common.ArtistAvatar
import app.shelf.ui.common.FavouritesCover
import app.shelf.ui.common.LoadContent
import app.shelf.ui.common.MosaicCover
import app.shelf.ui.common.plural
import app.shelf.ui.common.rememberLoad
import app.shelf.ui.covers.CaseCover
import app.shelf.ui.covers.albumColor
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import app.shelf.ui.theme.Shelf as Theme

private data class LibraryData(val playlists: List<PlaylistSummary>, val albums: List<Album>, val artists: List<ArtistSummary>)

private enum class Filter(val label: String) { Playlists("Playlists"), Albums("Albums"), Artists("Artists"), Downloaded("Downloaded") }

@Composable
fun LibraryScreen(source: LibrarySource, onFavourites: () -> Unit, onPlaylist: (Int) -> Unit, onAlbum: (Int) -> Unit, onArtist: (String) -> Unit,
                  signedOut: SignedOutHandler, onNewPlaylist: ((String) -> Unit)? = null,
                  onMakePlaylist: (suspend (String) -> String?)? = null, onImport: (() -> Unit)? = null) {
    var naming by rememberSaveable { mutableStateOf(false) }
    var making by rememberSaveable { mutableStateOf(false) }
    if (naming && onNewPlaylist != null) app.shelf.ui.common.NameDialog("New playlist", "", "Create", onNewPlaylist, { naming = false })
    if (making && onMakePlaylist != null) app.shelf.ui.common.MakePlaylistDialog(onMakePlaylist) { making = false }
    val (state, retry) = rememberLoad("library") {
        coroutineScope {
            val p = async { source.playlists() }; val a = async { source.albums("recent") }; val r = async { source.artists() }
            LibraryData(p.await(), a.await(), r.await())
        }
    }
    var filter by rememberSaveable { mutableStateOf<Filter?>(null) }
    val downloads = app.shelf.downloads.LocalDownloads.current
    val downloaded by (downloads?.items ?: kotlinx.coroutines.flow.MutableStateFlow(emptyList())).collectAsStateWithLifecycle()
    LoadContent(state, retry, signedOut) { d ->
        LazyColumn(Modifier.fillMaxSize()) {
            item {
                Column(Modifier.statusBarsPadding().padding(start = 16.dp, end = 16.dp, top = 18.dp)) {
                    Text("Library", style = MaterialTheme.typography.displayMedium, color = Theme.colors.ink)
                    Spacer(Modifier.height(10.dp))
                }
                LazyRow(contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    items(Filter.entries.filter { it != Filter.Downloaded || downloaded.isNotEmpty() }) { f ->
                        FilterChip(selected = filter == f, onClick = { filter = if (filter == f) null else f }, label = { Text(f.label) },
                            colors = FilterChipDefaults.filterChipColors(selectedContainerColor = Theme.colors.cobalt, selectedLabelColor = Theme.colors.cobaltInk,
                                labelColor = Theme.colors.ink))
                    }
                }
                Spacer(Modifier.height(8.dp))
            }
            if (filter == null || filter == Filter.Playlists) {
                if (onNewPlaylist != null) item {
                    LibraryRow("New playlist", "Make a playlist", { naming = true }) {
                        Box(Modifier.fillMaxSize().background(Theme.colors.sleeve), contentAlignment = Alignment.Center) {
                            androidx.compose.material3.Icon(androidx.compose.ui.res.painterResource(app.shelf.R.drawable.ic_plus), null, tint = Theme.colors.ink)
                        }
                    }
                }
                if (onMakePlaylist != null) item {
                    LibraryRow("Make a playlist", "From a genre, artist, mood or decade", { making = true }) {
                        Box(Modifier.fillMaxSize().background(Theme.colors.sleeve), contentAlignment = Alignment.Center) {
                            androidx.compose.material3.Icon(androidx.compose.ui.res.painterResource(app.shelf.R.drawable.ic_sparkle), null, tint = Theme.colors.ink)
                        }
                    }
                }
                if (onImport != null) item {
                    LibraryRow("Import a playlist", "From Spotify, YouTube or a file", onImport) {
                        Box(Modifier.fillMaxSize().background(Theme.colors.sleeve), contentAlignment = Alignment.Center) {
                            androidx.compose.material3.Icon(androidx.compose.ui.res.painterResource(app.shelf.R.drawable.ic_download), null, tint = Theme.colors.ink)
                        }
                    }
                }
                item { LibraryRow("Favourites", "Playlist", onFavourites) { FavouritesCover() } }
                items(d.playlists, key = { "p${it.id}" }) { p ->
                    LibraryRow(p.name, "Playlist, ${plural(p.trackCount, "song")}", { onPlaylist(p.id) }) {
                        MosaicCover(p.covers.mapNotNull { source.coverUrl(it.albumId, it.cover, 160) }, p.name, albumColor(null, p.name))
                    }
                }
            }
            if (filter == null || filter == Filter.Albums) items(d.albums, key = { "a${it.id}" }) { a ->
                LibraryRow(a.title, "Album, ${a.artist}", { onAlbum(a.id) }) {
                    CaseCover(source.coverUrl(a.id, a.cover, 160), a.title, albumColor(a.color, a.title))
                }
            }
            if (filter == null || filter == Filter.Artists) items(d.artists, key = { "r${it.name}" }) { r ->
                LibraryRow(r.name, "Artist", { onArtist(r.name) }) {
                    ArtistAvatar(r.coverAlbumId?.let { source.coverUrl(it, r.cover, 160) }, r.name, albumColor(null, r.name))
                }
            }
            if (filter == Filter.Downloaded) items(downloaded, key = { "d${it.key}" }) { c ->
                val open = { when (c.kind) { "album" -> onAlbum(c.id); "playlist" -> onPlaylist(c.id); else -> onFavourites() } }
                LibraryRow(c.name, listOf(c.kind.replaceFirstChar { it.uppercase() }, plural(c.tracks.size, "song")).joinToString(", "), open) {
                    when (c.kind) {
                        "album" -> CaseCover(source.coverUrl(c.id, c.covers.firstOrNull()?.cover, 160), c.name, albumColor(c.color, c.name))
                        "playlist" -> MosaicCover(c.covers.mapNotNull { source.coverUrl(it.albumId, it.cover, 160) }, c.name, albumColor(null, c.name))
                        else -> FavouritesCover()
                    }
                }
            }
            item { Spacer(Modifier.height(24.dp)) }
        }
    }
}

@Composable
private fun LibraryRow(title: String, subtitle: String, onClick: () -> Unit, cover: @Composable () -> Unit) {
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 16.dp, vertical = 7.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(56.dp)) { cover() }
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.titleMedium, color = Theme.colors.ink, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(subtitle, style = MaterialTheme.typography.bodySmall, color = Theme.colors.ink2, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
    }
}
