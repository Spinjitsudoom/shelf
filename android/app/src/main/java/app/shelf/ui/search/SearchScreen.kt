package app.shelf.ui.search

import android.content.Context
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import app.shelf.R
import app.shelf.data.ShelfApi
import app.shelf.data.Track
import app.shelf.playback.PlayContext
import app.shelf.ui.common.ArtistAvatar
import app.shelf.ui.common.Load
import app.shelf.ui.common.SectionTitle
import app.shelf.ui.common.TrackRow
import app.shelf.ui.common.fmtTime
import app.shelf.ui.common.plural
import app.shelf.ui.covers.CaseCover
import app.shelf.ui.covers.albumColor
import app.shelf.ui.theme.Shelf

/** The last few searches, kept on this phone. */
private class Recent(context: Context) {
    private val prefs = context.getSharedPreferences("search", Context.MODE_PRIVATE)
    fun all(): List<String> = prefs.getString("recent", "")!!.split('\n').filter { it.isNotBlank() }
    fun add(q: String) = prefs.edit().putString("recent", (listOf(q.trim()) + all().filter { it != q.trim() }).take(8).joinToString("\n")).apply()
    fun clear() = prefs.edit().remove("recent").apply()
}

@Composable
fun SearchScreen(api: ShelfApi, onPlay: (List<Track>, Int, PlayContext) -> Unit, onAlbum: (Int) -> Unit, onArtist: (String) -> Unit) {
    val vm: SearchViewModel = viewModel(factory = viewModelFactory { initializer { SearchViewModel(api::search) } })
    val query by vm.query.collectAsStateWithLifecycle()
    val results by vm.results.collectAsStateWithLifecycle()
    val recent = Recent(LocalContext.current)
    var recentList by remember { mutableStateOf(recent.all()) }
    val focus = remember { FocusRequester() }
    val keyboard = LocalSoftwareKeyboardController.current
    LaunchedEffect(Unit) { if (query.isEmpty()) focus.requestFocus() }
    fun remember(q: String) { if (q.isNotBlank()) { recent.add(q); recentList = recent.all() } }

    Column(Modifier.fillMaxSize()) {
        Column(Modifier.statusBarsPadding().padding(start = 16.dp, end = 16.dp, top = 18.dp, bottom = 8.dp)) {
            Text("Search", style = MaterialTheme.typography.displayMedium, color = Shelf.colors.ink)
            Spacer(Modifier.height(12.dp))
            TextField(
                value = query, onValueChange = vm::onQuery, singleLine = true,
                placeholder = { Text("Songs, albums and artists", color = Shelf.colors.ink2) },
                leadingIcon = { Icon(painterResource(R.drawable.ic_search), null, tint = Shelf.colors.ink2) },
                trailingIcon = if (query.isNotEmpty()) { { IconButton(onClick = { vm.onQuery("") }) { Icon(painterResource(R.drawable.ic_close), "Clear", tint = Shelf.colors.ink2) } } } else null,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                keyboardActions = KeyboardActions(onSearch = { remember(query); keyboard?.hide() }),
                shape = RoundedCornerShape(12.dp),
                colors = TextFieldDefaults.colors(focusedContainerColor = Shelf.colors.sleeve, unfocusedContainerColor = Shelf.colors.sleeve,
                    focusedIndicatorColor = androidx.compose.ui.graphics.Color.Transparent, unfocusedIndicatorColor = androidx.compose.ui.graphics.Color.Transparent,
                    cursorColor = Shelf.colors.cobalt, focusedTextColor = Shelf.colors.ink, unfocusedTextColor = Shelf.colors.ink),
                modifier = Modifier.fillMaxWidth().focusRequester(focus),
            )
        }
        when (val r = results) {
            null -> LazyColumn(Modifier.fillMaxSize()) {
                if (recentList.isNotEmpty()) {
                    item {
                        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                            SectionTitle("Recent searches", Modifier.weight(1f))
                            androidx.compose.material3.TextButton(onClick = { recent.clear(); recentList = emptyList() }) { Text("Clear", color = Shelf.colors.ink2) }
                        }
                    }
                    items(recentList) { q ->
                        Row(Modifier.fillMaxWidth().clickable { vm.onQuery(q) }.padding(horizontal = 16.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                            Icon(painterResource(R.drawable.ic_clock), null, tint = Shelf.colors.ink2, modifier = Modifier.size(20.dp))
                            Spacer(Modifier.width(14.dp))
                            Text(q, style = MaterialTheme.typography.bodyLarge, color = Shelf.colors.ink)
                        }
                    }
                } else item {
                    Text("Find anything on your shelf.", style = MaterialTheme.typography.bodyLarge, color = Shelf.colors.ink2, modifier = Modifier.padding(16.dp))
                }
            }
            Load.Loading -> Box(Modifier.fillMaxSize().padding(top = 40.dp), contentAlignment = Alignment.TopCenter) {
                CircularProgressIndicator(color = Shelf.colors.cobalt, strokeWidth = 3.dp)
            }
            is Load.Failed -> Text("Couldn’t search. Check the connection and try again.", style = MaterialTheme.typography.bodyMedium,
                color = Shelf.colors.ink2, modifier = Modifier.padding(16.dp))
            is Load.Ready -> {
                val res = r.value
                if (res.isEmpty) Text("Nothing on the shelf matches “$query”.", style = MaterialTheme.typography.bodyLarge, color = Shelf.colors.ink2, modifier = Modifier.padding(16.dp))
                else LazyColumn(Modifier.fillMaxSize()) {
                    if (res.artists.isNotEmpty()) item { SectionTitle("Artists") }
                    items(res.artists) { a ->
                        ResultRow(a.name, "Artist, ${plural(a.albums, "album")}", { remember(query); onArtist(a.name) }) {
                            ArtistAvatar(null, a.name, albumColor(null, a.name))
                        }
                    }
                    if (res.albums.isNotEmpty()) item { SectionTitle("Albums") }
                    items(res.albums) { a ->
                        ResultRow(a.title, "Album, ${a.artist}", { remember(query); onAlbum(a.id) }) {
                            CaseCover(api.coverUrl(a.id, a.cover, 160), a.title, albumColor(a.color, a.title))
                        }
                    }
                    if (res.tracks.isNotEmpty()) item { SectionTitle("Songs") }
                    itemsIndexed(res.tracks) { i, t ->
                        TrackRow(null, t.title, "${t.artist}, ${t.album}", fmtTime(t.duration),
                            { remember(query); onPlay(res.tracks, i, PlayContext("Search: $query", "search")) },
                            coverUrl = api.coverUrl(t.albumId, t.cover, 160), coverColor = albumColor(null, t.album), track = t)
                    }
                    item { Spacer(Modifier.height(24.dp)) }
                }
            }
        }
    }
}

@Composable
private fun ResultRow(title: String, subtitle: String, onClick: () -> Unit, cover: @Composable () -> Unit) {
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 16.dp, vertical = 7.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(52.dp)) { cover() }
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.titleMedium, color = Shelf.colors.ink, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(subtitle, style = MaterialTheme.typography.bodySmall, color = Shelf.colors.ink2, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
    }
}
