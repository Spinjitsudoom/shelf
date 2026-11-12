package app.shelf.ui.browse

import androidx.compose.foundation.background
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
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.shelf.R
import app.shelf.data.Episode
import app.shelf.data.LibrarySource
import app.shelf.data.PodcastResult
import app.shelf.data.PodcastsHome
import app.shelf.data.ShelfApi
import app.shelf.data.ShelfError
import app.shelf.playback.PlayContext
import app.shelf.ui.SignedOutHandler
import app.shelf.ui.common.LoadContent
import app.shelf.ui.common.SectionTitle
import app.shelf.ui.common.heroBrush
import app.shelf.ui.common.plural
import app.shelf.ui.common.rememberLoad
import app.shelf.ui.covers.CaseCover
import app.shelf.ui.covers.albumColor
import app.shelf.ui.theme.ArchivoDisplay
import kotlinx.coroutines.launch
import java.text.DateFormat
import java.util.Date
import app.shelf.ui.theme.Shelf as Theme

private fun length(seconds: Double): String {
    val min = Math.round(seconds / 60).toInt().coerceAtLeast(1)
    return if (min < 60) "$min min" else "${min / 60} hr" + if (min % 60 > 0) " ${min % 60} min" else ""
}

/** "12 Nov · 45 min", "12 min left" or "Played". */
private fun status(e: Episode): String {
    val day = e.published?.let { DateFormat.getDateInstance(DateFormat.MEDIUM).format(Date((it * 1000).toLong())) }
    val rest = when {
        e.finished -> "Played"
        e.position > 0 && e.duration > 0 -> "${length(e.duration - e.position)} left"
        e.duration > 0 -> length(e.duration)
        else -> null
    }
    return listOfNotNull(day, rest).joinToString(" · ")
}

fun playEpisode(e: Episode, onPlay: OnPlay) = onPlay(listOf(e.asTrack()), 0, PlayContext(e.album, "podcast/${e.podcastId}"))

/** One episode: the show (in mixed lists), when, how far you are; play it, or mark it played. */
@Composable
fun EpisodeRow(e: Episode, source: LibrarySource, onPlay: OnPlay, onMark: (Boolean) -> Unit, withShow: Boolean = false, onShow: ((Int) -> Unit)? = null) {
    var open by remember(e.id) { mutableStateOf(false) }
    Row(Modifier.fillMaxWidth().clickable { open = !open }.padding(horizontal = 16.dp, vertical = 12.dp), verticalAlignment = Alignment.Top) {
        if (withShow) {
            Box(Modifier.size(52.dp).clickable { onShow?.invoke(e.podcastId) }) {
                CaseCover(source.coverUrl(e.albumId, e.cover, 160), e.album, albumColor(null, e.album))
            }
            Spacer(Modifier.width(12.dp))
        }
        Column(Modifier.weight(1f)) {
            Text(listOfNotNull(if (withShow) e.album else null, status(e)).joinToString(" · "),
                style = MaterialTheme.typography.bodySmall, color = Theme.colors.ink2, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(e.title, style = MaterialTheme.typography.titleMedium, color = if (e.finished) Theme.colors.ink2 else Theme.colors.ink,
                maxLines = if (open) 6 else 2, overflow = TextOverflow.Ellipsis)
            if (e.description.isNotBlank()) Text(e.description, style = MaterialTheme.typography.bodySmall, color = Theme.colors.ink2,
                maxLines = if (open) 40 else 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 2.dp))
            if (e.position > 0 && e.duration > 0 && !e.finished) LinearProgressIndicator(
                progress = { (e.position / e.duration).toFloat().coerceIn(0f, 1f) },
                modifier = Modifier.padding(top = 6.dp).width(140.dp).height(3.dp),
                color = Theme.colors.cobalt, trackColor = Theme.colors.sleeve, drawStopIndicator = {})
        }
        IconButton(onClick = { onMark(!e.finished) }) {
            Icon(painterResource(R.drawable.ic_check), if (e.finished) "Mark as not played" else "Mark as played",
                tint = if (e.finished) Theme.colors.cobalt else Theme.colors.ink2)
        }
        IconButton(onClick = { playEpisode(e, onPlay) }, modifier = Modifier.padding(start = 2.dp).size(40.dp).background(Theme.colors.ink, CircleShape)) {
            Icon(painterResource(R.drawable.ic_play), if (e.position > 0 && !e.finished) "Resume ${e.title}" else "Play ${e.title}",
                tint = Theme.colors.tray, modifier = Modifier.size(18.dp))
        }
    }
}

/** Podcasts: find shows by name or link, go on with episodes, new ones, and your shows. */
@Composable
fun PodcastsScreen(api: ShelfApi, source: LibrarySource, onShow: (Int) -> Unit, onPlay: OnPlay, signedOut: SignedOutHandler, say: (String) -> Unit) {
    var reload by remember { mutableIntStateOf(0) }
    val (state, retry) = rememberLoad("podcasts", reload) { api.podcasts() }
    val scope = rememberCoroutineScope()
    val keyboard = LocalSoftwareKeyboardController.current
    var query by rememberSaveable { mutableStateOf("") }
    var results by remember { mutableStateOf<List<PodcastResult>?>(null) }
    var note by remember { mutableStateOf<String?>(null) }
    var adding by remember { mutableStateOf<String?>(null) }

    fun find() {
        val q = query.trim()
        if (q.length < 2) return
        keyboard?.hide()
        note = if (Regex("""^(https?://|\S+\.\S+)""").containsMatchIn(q)) "Reading that link…" else "Searching…"
        results = null
        scope.launch {
            try {
                val r = api.podcastSearch(q)
                results = r.results
                note = r.error ?: if (r.results.isEmpty()) "No shows found for “$q”. If you have its link, paste that instead." else null
            } catch (e: ShelfError) { note = e.message }
        }
    }
    val mark = { e: Episode, done: Boolean ->
        scope.launch { try { api.markEpisode(e.episodeId, done); reload++ } catch (x: ShelfError) { say(x.message ?: "Couldn’t reach the server") } }
        Unit
    }

    LazyColumn(Modifier.fillMaxSize()) {
        item {
            Column(Modifier.statusBarsPadding().padding(start = 16.dp, end = 16.dp, top = 18.dp, bottom = 8.dp)) {
                Text("Podcasts", style = MaterialTheme.typography.displayMedium, color = Theme.colors.ink)
                Text("Follow any show: search for it, or paste its link from Podbean, Apple Podcasts or anywhere else with a feed.",
                    style = MaterialTheme.typography.bodyMedium, color = Theme.colors.ink2, modifier = Modifier.padding(top = 4.dp))
                Spacer(Modifier.height(12.dp))
                TextField(
                    value = query, onValueChange = { query = it }, singleLine = true,
                    placeholder = { Text("Search for a show, or paste its link", color = Theme.colors.ink2) },
                    leadingIcon = { Icon(painterResource(R.drawable.ic_search), null, tint = Theme.colors.ink2) },
                    trailingIcon = if (query.isNotEmpty()) { { IconButton(onClick = { query = ""; results = null; note = null }) {
                        Icon(painterResource(R.drawable.ic_close), "Clear", tint = Theme.colors.ink2) } } } else null,
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                    keyboardActions = KeyboardActions(onSearch = { find() }),
                    shape = RoundedCornerShape(12.dp),
                    colors = TextFieldDefaults.colors(focusedContainerColor = Theme.colors.sleeve, unfocusedContainerColor = Theme.colors.sleeve,
                        focusedIndicatorColor = Color.Transparent, unfocusedIndicatorColor = Color.Transparent,
                        cursorColor = Theme.colors.cobalt, focusedTextColor = Theme.colors.ink, unfocusedTextColor = Theme.colors.ink),
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        }
        note?.let { n -> item { Text(n, color = Theme.colors.ink2, modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) } }
        results?.let { list ->
            items(list, key = { "r" + it.feedUrl }) { r ->
                Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 7.dp), verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.size(52.dp)) { CaseCover(r.image, r.title, albumColor(null, r.title)) }
                    Spacer(Modifier.width(12.dp))
                    Column(Modifier.weight(1f)) {
                        Text(r.title, style = MaterialTheme.typography.titleMedium, color = Theme.colors.ink, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text(listOfNotNull(r.author.ifBlank { null }, r.episodes?.let { plural(it, "episode") }).joinToString(" · "),
                            style = MaterialTheme.typography.bodySmall, color = Theme.colors.ink2, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    }
                    if (r.following && r.id != null) OutlinedButton(onClick = { onShow(r.id) }) { Text("Following", color = Theme.colors.cobalt) }
                    else Button(enabled = adding == null, onClick = {
                        adding = r.feedUrl
                        scope.launch {
                            try { val show = api.followPodcast(r.feedUrl); say("Following ${show.title}"); onShow(show.id) }
                            catch (e: ShelfError) { say(e.message ?: "Couldn’t add that show") }
                            adding = null
                        }
                    }, colors = ButtonDefaults.buttonColors(containerColor = Theme.colors.cobalt, contentColor = Theme.colors.cobaltInk)) {
                        Text(if (adding == r.feedUrl) "Adding…" else "Follow")
                    }
                }
            }
        }
        item {
            LoadContent(state, retry, signedOut) { d: PodcastsHome ->
                Column {
                    if (d.going.isNotEmpty()) {
                        SectionTitle("Continue listening")
                        d.going.forEach { e -> EpisodeRow(e, source, onPlay, { mark(e, it) }, withShow = true, onShow = onShow) }
                    }
                    if (d.new.isNotEmpty()) {
                        SectionTitle("New episodes")
                        d.new.forEach { e -> EpisodeRow(e, source, onPlay, { mark(e, it) }, withShow = true, onShow = onShow) }
                    }
                    if (d.shows.isNotEmpty()) {
                        SectionTitle("Your shows")
                        d.shows.forEach { s ->
                            Row(Modifier.fillMaxWidth().clickable { onShow(s.id) }.padding(horizontal = 16.dp, vertical = 7.dp), verticalAlignment = Alignment.CenterVertically) {
                                Box(Modifier.size(56.dp)) { CaseCover(source.coverUrl(s.albumId, s.cover, 160), s.title, albumColor(null, s.title)) }
                                Spacer(Modifier.width(14.dp))
                                Column(Modifier.weight(1f)) {
                                    Text(s.title, style = MaterialTheme.typography.titleMedium, color = Theme.colors.ink, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                    Text(if (s.unplayed > 0) "${plural(s.unplayed, "episode")} to hear" else "All heard",
                                        style = MaterialTheme.typography.bodySmall, color = Theme.colors.ink2)
                                }
                            }
                        }
                    } else if (results == null) {
                        Text("No shows yet. Search for one you like; new episodes of the shows you follow show up here and on Home.",
                            color = Theme.colors.ink2, modifier = Modifier.padding(16.dp))
                    }
                }
            }
        }
        item { Spacer(Modifier.height(24.dp)) }
    }
}

/** One show: about it, and its episodes, newest first. */
@Composable
fun PodcastScreen(id: Int, api: ShelfApi, source: LibrarySource, onPlay: OnPlay, onBack: () -> Unit, signedOut: SignedOutHandler, say: (String) -> Unit) {
    var reload by remember { mutableIntStateOf(0) }
    val (state, retry) = rememberLoad("podcast", id, reload) { api.podcast(id) }
    val scope = rememberCoroutineScope()
    var unheard by rememberSaveable { mutableStateOf(false) }
    var aboutOpen by remember { mutableStateOf(false) }
    LoadContent(state, retry, signedOut) { s ->
        val color = albumColor(null, s.title)
        val next = s.episodeList.firstOrNull { it.position > 0 && !it.finished } ?: s.episodeList.firstOrNull { !it.finished }
        val shown = if (unheard) s.episodeList.filter { !it.finished } else s.episodeList
        Box(Modifier.fillMaxSize()) {
            LazyColumn(Modifier.fillMaxSize()) {
                item {
                    Column(Modifier.fillMaxWidth().background(heroBrush(color, Theme.colors.tray)).statusBarsPadding()
                        .padding(start = 20.dp, end = 20.dp, top = 56.dp, bottom = 12.dp)) {
                        Box(Modifier.size(180.dp)) { CaseCover(source.coverUrl(s.albumId, s.cover, 512), s.title, color) }
                        Spacer(Modifier.height(14.dp))
                        Text("PODCAST", style = MaterialTheme.typography.labelMedium, color = Theme.colors.ink2, fontWeight = FontWeight.Bold)
                        Text(s.title, style = pageTitleStyle(s.title).copy(fontFamily = ArchivoDisplay), color = Theme.colors.ink)
                        if (s.author.isNotBlank()) Text(s.author, style = MaterialTheme.typography.titleMedium, color = Theme.colors.ink)
                        Text(listOf(plural(s.episodes, "episode"), if (s.unplayed > 0) "${s.unplayed} to hear" else "all heard").joinToString(", "),
                            style = MaterialTheme.typography.bodyMedium, color = Theme.colors.ink2)
                        Spacer(Modifier.height(12.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
                            if (next != null) Button(onClick = { playEpisode(next, onPlay) },
                                colors = ButtonDefaults.buttonColors(containerColor = Theme.colors.cobalt, contentColor = Theme.colors.cobaltInk)) {
                                Icon(painterResource(R.drawable.ic_play), null, Modifier.size(20.dp)); Spacer(Modifier.size(8.dp))
                                Text(if (next.position > 0) "Resume" else "Play latest")
                            }
                            OutlinedButton(onClick = {
                                scope.launch {
                                    try {
                                        if (s.following) { api.unfollowPodcast(s.id); say("Stopped following ${s.title}"); onBack() }
                                        else { api.followPodcast(s.feedUrl); reload++ }
                                    } catch (e: ShelfError) { say(e.message ?: "Couldn’t reach the server") }
                                }
                            }) { Text(if (s.following) "Following" else "Follow", color = if (s.following) Theme.colors.cobalt else Theme.colors.ink) }
                            if (s.following) IconButton(onClick = {
                                scope.launch {
                                    try { val r = api.refreshPodcast(s.id); say(if (r.new > 0) plural(r.new, "new episode") else "No new episodes yet"); reload++ }
                                    catch (e: ShelfError) { say(e.message ?: "Couldn’t reach the server") }
                                }
                            }) { Icon(painterResource(R.drawable.ic_refresh), "Check for new episodes", tint = Theme.colors.ink) }
                        }
                    }
                }
                if (s.description.isNotBlank()) item {
                    Text(s.description, style = MaterialTheme.typography.bodyMedium, color = Theme.colors.ink2,
                        maxLines = if (aboutOpen) 60 else 3, overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.clickable { aboutOpen = !aboutOpen }.padding(horizontal = 20.dp, vertical = 8.dp))
                }
                item {
                    Row(Modifier.padding(horizontal = 16.dp, vertical = 4.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        listOf(false to "All", true to "Not played").forEach { (on, label) ->
                            FilterChip(selected = unheard == on, onClick = { unheard = on }, label = { Text(label) },
                                colors = FilterChipDefaults.filterChipColors(selectedContainerColor = Theme.colors.cobalt, selectedLabelColor = Theme.colors.cobaltInk,
                                    labelColor = Theme.colors.ink))
                        }
                    }
                }
                itemsIndexed(shown, key = { _, e -> e.id }) { i, e ->
                    if (i > 0) HorizontalDivider(Modifier.padding(horizontal = 16.dp), color = Theme.colors.sleeve)
                    EpisodeRow(e, source, onPlay, { done ->
                        scope.launch { try { api.markEpisode(e.episodeId, done); reload++ } catch (x: ShelfError) { say(x.message ?: "Couldn’t reach the server") } }
                    })
                }
                if (shown.isEmpty()) item { Text("You’ve heard every episode.", color = Theme.colors.ink2, modifier = Modifier.padding(16.dp)) }
                item { Spacer(Modifier.height(24.dp)) }
            }
            IconButton(onClick = onBack, modifier = Modifier.statusBarsPadding().padding(4.dp)) {
                Icon(painterResource(R.drawable.ic_back), contentDescription = "Back", tint = Theme.colors.ink)
            }
        }
    }
}
