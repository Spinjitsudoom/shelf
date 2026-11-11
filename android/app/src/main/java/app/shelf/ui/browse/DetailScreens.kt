package app.shelf.ui.browse

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import kotlinx.coroutines.launch
import app.shelf.data.LibrarySource
import app.shelf.data.Track
import app.shelf.playback.PlayContext
import app.shelf.ui.SignedOutHandler
import app.shelf.ui.Routes
import app.shelf.ui.common.ArtistLinks
import app.shelf.ui.common.FavouritesCover
import app.shelf.ui.common.LoadContent
import app.shelf.ui.common.MosaicCover
import app.shelf.ui.common.fmtLength
import app.shelf.ui.common.plural
import app.shelf.ui.common.rememberLoad
import app.shelf.ui.covers.CaseCover
import app.shelf.ui.covers.TapeCover
import app.shelf.ui.covers.albumColor
import app.shelf.ui.theme.Shelf

typealias OnPlay = (tracks: List<Track>, index: Int, context: PlayContext) -> Unit

private fun facts(vararg parts: String?) = parts.filterNotNull().filter { it.isNotBlank() }.joinToString(", ")
private fun LibrarySource.cover(t: Track) = coverUrl(t.albumId, t.cover, 160)

@Composable
fun AlbumScreen(id: Int, source: LibrarySource, onPlay: OnPlay, onArtist: (String) -> Unit, onBack: () -> Unit, signedOut: SignedOutHandler) {
    val (state, retry) = rememberLoad(id) { source.album(id) }
    LoadContent(state, retry, signedOut) { a ->
        val color = albumColor(a.color, a.title)
        val ctx = PlayContext(a.title, Routes.album(a.id))
        TrackListPage(
            color = color, kind = null, title = a.title,
            cover = { CaseCover(source.coverUrl(a.id, a.cover, 640), a.title, color) },
            byline = { ArtistLinks(a.artist, a.artists, onArtist) },
            facts = facts(a.year?.toString(), plural(a.tracks.size, "song"), fmtLength(a.duration)),
            tracks = a.tracks, numbered = true, coverUrl = { null },
            onTrack = { onPlay(a.tracks, it, ctx) }, onShuffle = { onPlay(a.tracks.shuffled(), 0, ctx) }, onBack = onBack,
            actions = {
                app.shelf.ui.common.DownloadButton(app.shelf.downloads.Downloadable("album", a.id, a.title, a.artist, a.color,
                    listOf(app.shelf.data.CoverRef(a.id, a.cover)), a.tracks))
                app.shelf.ui.common.ShareLinkButton("album", a.id, a.title, a.artist)
            },
        )
    }
}

@Composable
fun PlaylistScreen(id: Int, source: LibrarySource, onPlay: OnPlay, onBack: () -> Unit, signedOut: SignedOutHandler,
                   api: app.shelf.data.ShelfApi? = null, say: (String) -> Unit = {},
                   onTransition: (entryId: Int, transition: kotlinx.serialization.json.JsonElement) -> Unit = { _, _ -> }) {
    var picking by androidx.compose.runtime.remember { androidx.compose.runtime.mutableStateOf<Int?>(null) }
    // Transitions just picked, shown straight away (no reload).
    var picked by androidx.compose.runtime.remember { androidx.compose.runtime.mutableStateOf(mapOf<Int, kotlinx.serialization.json.JsonElement>()) }
    val (state, retry) = rememberLoad(id) { source.playlist(id) }
    var menu by androidx.compose.runtime.remember { androidx.compose.runtime.mutableStateOf(false) }
    var renaming by androidx.compose.runtime.remember { androidx.compose.runtime.mutableStateOf(false) }
    var deleting by androidx.compose.runtime.remember { androidx.compose.runtime.mutableStateOf(false) }
    var reordering by androidx.compose.runtime.remember { androidx.compose.runtime.mutableStateOf(false) }
    val scope = androidx.compose.runtime.rememberCoroutineScope()
    /** Run a change on the server, then reload; say what went wrong if it didn't work. */
    fun change(done: String?, block: suspend () -> Unit) {
        scope.launch {
            try { block(); done?.let(say); retry() } catch (e: app.shelf.data.ShelfError) { say("Couldn’t save that. Check the connection and try again.") }
        }
    }
    LoadContent(state, retry, signedOut) { loaded ->
        val p = loaded.copy(tracks = loaded.tracks.map { t -> t.entryId?.let(picked::get)?.let { t.copy(transition = it) } ?: t })
        val color = albumColor(null, p.name)
        val ctx = PlayContext(p.name, Routes.playlist(p.id), mix = p.mix) // Mix on: songs hand over like a DJ set
        val editable = p.canEdit && api != null
        if (reordering) {
            ReorderList(p.name, p.tracks, onDone = { order -> reordering = false
                change("Saved the new order") { api!!.reorderPlaylist(p.id, order.mapNotNull { it.entryId }) } }, onCancel = { reordering = false })
            return@LoadContent
        }
        TrackListPage(
            color = color, kind = "Playlist", title = p.name,
            cover = { MosaicCover(p.covers.mapNotNull { source.coverUrl(it.albumId, it.cover, 320) }, p.name, color) },
            byline = playlistByline(p.description, p.rulesText)?.let { { Text(it, style = MaterialTheme.typography.bodyMedium, color = Shelf.colors.ink2) } },
            facts = facts(plural(p.tracks.size, "song"), fmtLength(p.tracks.sumOf { it.duration }), if (p.mix) "Mix on" else null),
            tracks = p.tracks, numbered = false, coverUrl = { source.cover(it) },
            onTrack = { onPlay(p.tracks, it, ctx) }, onShuffle = { onPlay(p.tracks.shuffled(), 0, ctx) }, onBack = onBack,
            between = if (p.mix) { i -> TransitionPill(p.tracks[i], p.tracks[i + 1]) { picking = i } } else null,
            onRemove = if (editable) { i -> p.tracks[i].entryId?.let { e -> change("Removed from ${p.name}") { api!!.removeFromPlaylist(p.id, e) } } } else null,
            actions = {
                app.shelf.ui.common.DownloadButton(app.shelf.downloads.Downloadable("playlist", p.id, p.name, p.description ?: "", null, p.covers, p.tracks))
                app.shelf.ui.common.ShareLinkButton("playlist", p.id, p.name, null)
                if (editable) androidx.compose.foundation.layout.Box {
                    androidx.compose.material3.OutlinedIconButton(onClick = { menu = true }) {
                        androidx.compose.material3.Icon(androidx.compose.ui.res.painterResource(app.shelf.R.drawable.ic_edit), "Edit playlist", tint = Shelf.colors.ink)
                    }
                    androidx.compose.material3.DropdownMenu(menu, { menu = false }, containerColor = Shelf.colors.sleeve) {
                        androidx.compose.material3.DropdownMenuItem({ Text("Rename") }, { menu = false; renaming = true })
                        if (p.tracks.size > 1) androidx.compose.material3.DropdownMenuItem({ Text("Reorder songs") }, { menu = false; reordering = true })
                        androidx.compose.material3.DropdownMenuItem({ Text(if (p.mix) "Turn Mix off" else "Turn Mix on (songs blend like a DJ set)") },
                            { menu = false; change(if (p.mix) "Mix off" else "Mix on") { api!!.setPlaylistMix(p.id, !p.mix) } })
                        androidx.compose.material3.DropdownMenuItem({ Text("Delete playlist") }, { menu = false; deleting = true })
                    }
                }
            },
        )
        picking?.let { i ->
            val cur = p.tracks.getOrNull(i); val nxt = p.tracks.getOrNull(i + 1)
            if (cur != null && nxt != null) TransitionSheet(cur, nxt, editable && cur.entryId != null, onSave = { choice ->
                val e = cur.entryId ?: return@TransitionSheet
                val before = picked
                picked = picked + (e to choice.toJson())
                onTransition(e, choice.toJson())
                scope.launch {
                    try { api!!.setTransition(p.id, e, choice) } catch (ex: app.shelf.data.ShelfError) {
                        picked = before
                        onTransition(e, cur.transition ?: kotlinx.serialization.json.JsonPrimitive("auto"))
                        say("Couldn’t save that. Check the connection and try again.")
                    }
                }
            }, onDismiss = { picking = null })
        }
        if (renaming) {
            var newName = p.name
            app.shelf.ui.common.NameDialog("Rename playlist", p.name, "Save", { n -> newName = n },
                { renaming = false }, description = p.description ?: "", onDescription = { d -> change(null) { api!!.editPlaylist(p.id, name = newName, description = d) } })
        }
        if (deleting) app.shelf.ui.common.ConfirmDialog("Delete “${p.name}”?", "The playlist goes from every device. The songs stay on your shelf.", "Delete",
            { scope.launch { try { api!!.deletePlaylist(p.id); say("Deleted ${p.name}"); onBack() } catch (e: app.shelf.data.ShelfError) { say("Couldn’t delete it. Check the connection and try again.") } } },
            { deleting = false })
    }
}

/** A Blend with someone: the same page as a mix. */
@Composable
fun BlendScreen(otherId: Int, api: app.shelf.data.ShelfApi, onPlay: OnPlay, onBack: () -> Unit, signedOut: SignedOutHandler) {
    val (state, retry) = rememberLoad("blend", otherId) { api.blend(otherId) }
    LoadContent(state, retry, signedOut) { m ->
        val color = albumColor(m.color, m.name)
        val ctx = PlayContext(m.name, "blend/$otherId")
        TrackListPage(
            color = color, kind = "Blend", title = m.name,
            cover = { TapeCover(m.name, color, m.covers.mapNotNull { api.coverUrl(it.albumId, it.cover, 160) }) },
            byline = m.description.takeIf { it.isNotBlank() }?.let { { Text(it, style = MaterialTheme.typography.bodyMedium, color = Shelf.colors.ink2) } },
            facts = facts(plural(m.tracks.size, "song"), fmtLength(m.tracks.sumOf { it.duration })),
            tracks = m.tracks, numbered = false, coverUrl = { api.coverUrl(it.albumId, it.cover, 160) },
            onTrack = { onPlay(m.tracks, it, ctx) }, onShuffle = { onPlay(m.tracks.shuffled(), 0, ctx) }, onBack = onBack,
        )
    }
}

/** Song or artist radio: the same page as a mix. */
@Composable
fun RadioScreen(track: Int?, artist: String?, api: app.shelf.data.ShelfApi, onPlay: OnPlay, onBack: () -> Unit, signedOut: SignedOutHandler) {
    val (state, retry) = rememberLoad(track, artist) { api.radio(track = track, artist = artist) }
    LoadContent(state, retry, signedOut) { m ->
        val color = albumColor(m.color, m.name)
        val ctx = PlayContext(m.name, if (track != null) "radio/track/$track" else "radio/artist/${android.net.Uri.encode(artist)}")
        TrackListPage(
            color = color, kind = "Radio", title = m.name,
            cover = { TapeCover(m.name, color, m.covers.mapNotNull { api.coverUrl(it.albumId, it.cover, 160) }) },
            byline = m.description.takeIf { it.isNotBlank() }?.let { { Text(it, style = MaterialTheme.typography.bodyMedium, color = Shelf.colors.ink2) } },
            facts = facts(plural(m.tracks.size, "song"), fmtLength(m.tracks.sumOf { it.duration })),
            tracks = m.tracks, numbered = false, coverUrl = { api.coverUrl(it.albumId, it.cover, 160) },
            onTrack = { onPlay(m.tracks, it, ctx) }, onShuffle = { onPlay(m.tracks.shuffled(), 0, ctx) }, onBack = onBack,
        )
    }
}

@Composable
fun MixScreen(key: String, source: LibrarySource, onPlay: OnPlay, onBack: () -> Unit, signedOut: SignedOutHandler) {
    val (state, retry) = rememberLoad(key) { source.mix(key) }
    LoadContent(state, retry, signedOut) { m ->
        val color = albumColor(m.color, m.name)
        val ctx = PlayContext(m.name, Routes.mix(m.key))
        TrackListPage(
            color = color, kind = "Made for you", title = m.name,
            cover = { TapeCover(m.name, color, m.covers.mapNotNull { source.coverUrl(it.albumId, it.cover, 160) }) },
            byline = m.description.takeIf { it.isNotBlank() }?.let { { Text(it, style = MaterialTheme.typography.bodyMedium, color = Shelf.colors.ink2) } },
            facts = facts(plural(m.tracks.size, "song"), fmtLength(m.tracks.sumOf { it.duration })),
            tracks = m.tracks, numbered = false, coverUrl = { source.cover(it) },
            onTrack = { onPlay(m.tracks, it, ctx) }, onShuffle = { onPlay(m.tracks.shuffled(), 0, ctx) }, onBack = onBack,
        )
    }
}

@Composable
fun FavouritesScreen(source: LibrarySource, onPlay: OnPlay, onBack: () -> Unit, signedOut: SignedOutHandler) {
    val (state, retry) = rememberLoad("favourites") { source.likes() }
    LoadContent(state, retry, signedOut) { tracks ->
        val ctx = PlayContext("Favourites", Routes.FAVOURITES)
        TrackListPage(
            color = Shelf.colors.cobalt, kind = "Playlist", title = "Favourites",
            cover = { FavouritesCover() }, byline = null,
            facts = facts(plural(tracks.size, "song"), fmtLength(tracks.sumOf { it.duration })),
            tracks = tracks, numbered = false, coverUrl = { source.cover(it) },
            onTrack = { onPlay(tracks, it, ctx) }, onShuffle = { onPlay(tracks.shuffled(), 0, ctx) }, onBack = onBack,
            actions = { app.shelf.ui.common.DownloadButton(app.shelf.downloads.Downloadable("favourites", 0, "Favourites", tracks = tracks)) },
        )
    }
}

/** Under a playlist's name: its description, and a smart playlist's rules. */
fun playlistByline(description: String?, rulesText: String?): String? =
    listOfNotNull(description?.takeIf { it.isNotBlank() }, rulesText?.takeIf { it.isNotBlank() }?.let { "$it." })
        .joinToString("\n").ifEmpty { null }
