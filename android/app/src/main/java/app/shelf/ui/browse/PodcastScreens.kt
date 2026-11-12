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
import androidx.compose.ui.graphics.compositeOver
import androidx.compose.foundation.layout.offset
import androidx.lifecycle.compose.collectAsStateWithLifecycle
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

/** An episode as a download: one "song" the phone keeps, shown under Downloads and in Your Episodes. */
fun episodeDownload(e: Episode) = app.shelf.downloads.Downloadable("episode", e.episodeId, e.title, e.album,
    covers = listOf(app.shelf.data.CoverRef(e.albumId, e.cover)), tracks = listOf(e.asTrack()))

/** A downloaded episode, back as an episode (offline: what the phone kept of it). */
fun app.shelf.downloads.Downloadable.asEpisode(): Episode? = tracks.firstOrNull()?.let { t ->
    Episode(t.id, t.episodeId ?: id, t.podcastId ?: 0, t.title, t.album, t.albumId, t.cover, t.duration, t.codec, saved = true)
}

/**
 * One episode: the show (in mixed lists), when, how far you are; keep it in Your Episodes,
 * download it, mark it played, play it. Saving and downloading need [api].
 */
@Composable
fun EpisodeRow(e: Episode, source: LibrarySource, onPlay: OnPlay, onMark: (Boolean) -> Unit, withShow: Boolean = false, onShow: ((Int) -> Unit)? = null,
               api: ShelfApi? = null, say: (String) -> Unit = {}, onSaved: ((Boolean) -> Unit)? = null) {
    var open by remember(e.id) { mutableStateOf(false) }
    var saved by remember(e.id, e.saved) { mutableStateOf(e.saved) }
    val scope = rememberCoroutineScope()
    val downloads = app.shelf.downloads.LocalDownloads.current
    val items by (downloads?.items ?: kotlinx.coroutines.flow.MutableStateFlow(emptyList())).collectAsStateWithLifecycle()
    val progress by (downloads?.progress ?: kotlinx.coroutines.flow.MutableStateFlow(emptyMap())).collectAsStateWithLifecycle()
    val dl = remember(e.episodeId) { episodeDownload(e) }
    val downloaded = items.any { it.key == dl.key }
    val dlDone = downloaded && (progress[dl.key] ?: 0f) >= 1f
    fun keep(on: Boolean) {
        val a = api ?: return
        scope.launch {
            try {
                a.saveEpisode(e.episodeId, on)
                saved = on
                if (!on && downloaded) downloads?.remove(dl.kind, dl.id)
                say(if (on) "Saved to Your Episodes" else "Removed from Your Episodes")
                onSaved?.invoke(on)
            } catch (x: ShelfError) { say(x.message ?: "Couldn’t reach the server") }
        }
    }
    fun download() {
        val d = downloads ?: return
        if (downloaded) { d.remove(dl.kind, dl.id); say("Removed from downloads"); return }
        val a = api ?: return
        scope.launch {
            try {
                if (!saved) { a.saveEpisode(e.episodeId, true); saved = true; onSaved?.invoke(true) }
                d.download(dl)
                say("Downloading “${e.title}”")
            } catch (x: ShelfError) { say(x.message ?: "Couldn’t reach the server") }
        }
    }
    Row(Modifier.fillMaxWidth().clickable { open = !open }.padding(start = 16.dp, end = 16.dp, top = 12.dp, bottom = 4.dp), verticalAlignment = Alignment.Top) {
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
            Row(Modifier.padding(top = 2.dp).offset(x = (-12).dp), verticalAlignment = Alignment.CenterVertically) {
                if (api != null) IconButton(onClick = { keep(!saved) }) {
                    Icon(painterResource(if (saved) R.drawable.ic_saved else R.drawable.ic_save),
                        if (saved) "Remove from Your Episodes" else "Save to Your Episodes", tint = if (saved) Theme.colors.cobalt else Theme.colors.ink2)
                }
                if (api != null && downloads != null) IconButton(onClick = { download() }) {
                    when {
                        dlDone -> Icon(painterResource(R.drawable.ic_downloaded), "Downloaded. Remove the download", tint = Theme.colors.cobalt)
                        downloaded -> Box(contentAlignment = Alignment.Center) {
                            androidx.compose.material3.CircularProgressIndicator(progress = { progress[dl.key] ?: 0f }, modifier = Modifier.size(22.dp),
                                color = Theme.colors.cobalt, trackColor = Theme.colors.ink.copy(alpha = .15f), strokeWidth = 2.dp)
                        }
                        else -> Icon(painterResource(R.drawable.ic_download), "Download", tint = Theme.colors.ink2)
                    }
                }
                IconButton(onClick = { onMark(!e.finished) }) {
                    Icon(painterResource(R.drawable.ic_check), if (e.finished) "Mark as not played" else "Mark as played",
                        tint = if (e.finished) Theme.colors.cobalt else Theme.colors.ink2)
                }
            }
        }
        IconButton(onClick = { playEpisode(e, onPlay) }, modifier = Modifier.align(Alignment.CenterVertically).padding(start = 6.dp).size(40.dp).background(Theme.colors.ink, CircleShape)) {
            Icon(painterResource(R.drawable.ic_play), if (e.position > 0 && !e.finished) "Resume ${e.title}" else "Play ${e.title}",
                tint = Theme.colors.tray, modifier = Modifier.size(18.dp))
        }
    }
}

private enum class EpisodeFilter(val label: String) { Unplayed("Unplayed"), Downloaded("Downloaded"), Going("In progress") }

/** Your Episodes: the episodes you saved or downloaded, like a playlist of them, with filters. */
@Composable
fun YourEpisodesScreen(api: ShelfApi, source: LibrarySource, username: String?, onPlay: OnPlay, onShow: (Int) -> Unit, onBack: () -> Unit,
                       signedOut: SignedOutHandler, say: (String) -> Unit) {
    var reload by remember { mutableIntStateOf(0) }
    val downloads = app.shelf.downloads.LocalDownloads.current
    val items by (downloads?.items ?: kotlinx.coroutines.flow.MutableStateFlow(emptyList())).collectAsStateWithLifecycle()
    val (state, retry) = rememberLoad("your-episodes", reload) {
        try { api.savedEpisodes() to false }
        catch (e: ShelfError.Offline) { emptyList<Episode>() to true } // offline: the downloaded ones, below
    }
    val scope = rememberCoroutineScope()
    var filter by rememberSaveable { mutableStateOf<EpisodeFilter?>(null) }
    var byRelease by rememberSaveable { mutableStateOf(false) }
    LoadContent(state, retry, signedOut, onBack) { (fromServer, away) ->
        val kept = items.filter { it.kind == "episode" }
        val keptIds = kept.map { it.id }.toSet()
        val all = fromServer + kept.mapNotNull { it.asEpisode() }.filter { k -> fromServer.none { it.episodeId == k.episodeId } }
        val shown = all.filter { e ->
            when (filter) {
                EpisodeFilter.Unplayed -> !e.finished
                EpisodeFilter.Downloaded -> e.episodeId in keptIds
                EpisodeFilter.Going -> e.position > 0 && !e.finished
                null -> true
            }
        }.let { l -> if (byRelease) l.sortedByDescending { it.published ?: 0.0 } else l.sortedByDescending { it.savedAt ?: 0.0 } }
        val mark = { e: Episode, done: Boolean ->
            scope.launch { try { api.markEpisode(e.episodeId, done); reload++ } catch (x: ShelfError) { say(x.message ?: "Couldn’t reach the server") } }
            Unit
        }
        Box(Modifier.fillMaxSize()) {
            LazyColumn(Modifier.fillMaxSize()) {
                item {
                    Column(Modifier.fillMaxWidth().background(heroBrush(Theme.colors.cobalt, Theme.colors.tray)).statusBarsPadding()
                        .padding(start = 20.dp, end = 20.dp, top = 56.dp, bottom = 12.dp)) {
                        YourEpisodesCover(Modifier.size(160.dp))
                        Spacer(Modifier.height(14.dp))
                        Text("PLAYLIST", style = MaterialTheme.typography.labelMedium, color = Theme.colors.ink2, fontWeight = FontWeight.Bold)
                        Text("Your Episodes", style = pageTitleStyle("Your Episodes").copy(fontFamily = ArchivoDisplay), color = Theme.colors.ink)
                        Text(listOfNotNull(username, plural(all.size, "episode")).joinToString(" • "),
                            style = MaterialTheme.typography.bodyMedium, color = Theme.colors.ink2)
                        if (away) Text("You’re offline: these are the ones downloaded to this phone.",
                            style = MaterialTheme.typography.bodySmall, color = Theme.colors.ink2, modifier = Modifier.padding(top = 4.dp))
                        Spacer(Modifier.height(12.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
                            val toPlay = shown.filter { !it.finished }
                            if (toPlay.isNotEmpty()) Button(onClick = {
                                onPlay(toPlay.map { it.asTrack() }, 0, PlayContext("Your Episodes", "episodes"))
                            }, colors = ButtonDefaults.buttonColors(containerColor = Theme.colors.cobalt, contentColor = Theme.colors.cobaltInk)) {
                                Icon(painterResource(R.drawable.ic_play), null, Modifier.size(20.dp)); Spacer(Modifier.size(8.dp)); Text("Play")
                            }
                            OutlinedButton(onClick = { byRelease = !byRelease }) {
                                Icon(painterResource(R.drawable.ic_sort), null, Modifier.size(18.dp), tint = Theme.colors.ink); Spacer(Modifier.size(6.dp))
                                Text(if (byRelease) "Release date" else "Recently added", color = Theme.colors.ink)
                            }
                        }
                    }
                }
                item {
                    androidx.compose.foundation.lazy.LazyRow(contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 16.dp, vertical = 4.dp),
                        horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        items(EpisodeFilter.entries) { f ->
                            FilterChip(selected = filter == f, onClick = { filter = if (filter == f) null else f }, label = { Text(f.label) },
                                colors = FilterChipDefaults.filterChipColors(selectedContainerColor = Theme.colors.cobalt, selectedLabelColor = Theme.colors.cobaltInk,
                                    labelColor = Theme.colors.ink))
                        }
                    }
                }
                itemsIndexed(shown, key = { _, e -> e.id }) { i, e ->
                    if (i > 0) HorizontalDivider(Modifier.padding(horizontal = 16.dp), color = Theme.colors.sleeve)
                    EpisodeRow(e, source, onPlay, { mark(e, it) }, withShow = true, onShow = onShow, api = api, say = say,
                        onSaved = { on -> if (!on) reload++ })
                }
                if (shown.isEmpty()) item {
                    Text(if (all.isEmpty()) "Nothing saved yet. Save an episode with the bookmark next to it, or download it, and it shows up here."
                        else "Nothing here with that filter.", color = Theme.colors.ink2, modifier = Modifier.padding(16.dp))
                }
                item { Spacer(Modifier.height(24.dp)) }
            }
            IconButton(onClick = onBack, modifier = Modifier.statusBarsPadding().padding(4.dp)) {
                Icon(painterResource(R.drawable.ic_back), contentDescription = "Back", tint = Theme.colors.ink)
            }
        }
    }
}

/** Your Episodes' cover: a bookmark on blue. */
@Composable
fun YourEpisodesCover(modifier: Modifier = Modifier) {
    Box(modifier.background(androidx.compose.ui.graphics.Brush.linearGradient(listOf(Theme.colors.cobalt, Theme.colors.cobalt.copy(alpha = .6f).compositeOver(Color.Black))),
        RoundedCornerShape(4.dp)), contentAlignment = Alignment.Center) {
        Icon(painterResource(R.drawable.ic_saved), null, tint = Color.White, modifier = Modifier.fillMaxSize(.42f))
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
                        d.going.forEach { e -> EpisodeRow(e, source, onPlay, { mark(e, it) }, withShow = true, onShow = onShow, api = api, say = say) }
                    }
                    if (d.new.isNotEmpty()) {
                        SectionTitle("New episodes")
                        d.new.forEach { e -> EpisodeRow(e, source, onPlay, { mark(e, it) }, withShow = true, onShow = onShow, api = api, say = say) }
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
    LoadContent(state, retry, signedOut, onBack) { s ->
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
                    }, api = api, say = say)
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
