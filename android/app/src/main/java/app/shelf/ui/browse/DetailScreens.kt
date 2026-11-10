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
            actions = { app.shelf.ui.common.DownloadButton(app.shelf.downloads.Downloadable("album", a.id, a.title, a.artist, a.color,
                listOf(app.shelf.data.CoverRef(a.id, a.cover)), a.tracks)) },
        )
    }
}

@Composable
fun PlaylistScreen(id: Int, source: LibrarySource, onPlay: OnPlay, onBack: () -> Unit, signedOut: SignedOutHandler,
                   api: app.shelf.data.ShelfApi? = null, say: (String) -> Unit = {}) {
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
    LoadContent(state, retry, signedOut) { p ->
        val color = albumColor(null, p.name)
        val ctx = PlayContext(p.name, Routes.playlist(p.id))
        val editable = p.canEdit && api != null
        if (reordering) {
            ReorderList(p.name, p.tracks, onDone = { order -> reordering = false
                change("Saved the new order") { api!!.reorderPlaylist(p.id, order.mapNotNull { it.entryId }) } }, onCancel = { reordering = false })
            return@LoadContent
        }
        TrackListPage(
            color = color, kind = "Playlist", title = p.name,
            cover = { MosaicCover(p.covers.mapNotNull { source.coverUrl(it.albumId, it.cover, 320) }, p.name, color) },
            byline = p.description?.takeIf { it.isNotBlank() }?.let { { Text(it, style = MaterialTheme.typography.bodyMedium, color = Shelf.colors.ink2) } },
            facts = facts(plural(p.tracks.size, "song"), fmtLength(p.tracks.sumOf { it.duration })),
            tracks = p.tracks, numbered = false, coverUrl = { source.cover(it) },
            onTrack = { onPlay(p.tracks, it, ctx) }, onShuffle = { onPlay(p.tracks.shuffled(), 0, ctx) }, onBack = onBack,
            onRemove = if (editable) { i -> p.tracks[i].entryId?.let { e -> change("Removed from ${p.name}") { api!!.removeFromPlaylist(p.id, e) } } } else null,
            actions = {
                app.shelf.ui.common.DownloadButton(app.shelf.downloads.Downloadable("playlist", p.id, p.name, p.description ?: "", null, p.covers, p.tracks))
                if (editable) androidx.compose.foundation.layout.Box {
                    androidx.compose.material3.OutlinedIconButton(onClick = { menu = true }) {
                        androidx.compose.material3.Icon(androidx.compose.ui.res.painterResource(app.shelf.R.drawable.ic_edit), "Edit playlist", tint = Shelf.colors.ink)
                    }
                    androidx.compose.material3.DropdownMenu(menu, { menu = false }, containerColor = Shelf.colors.sleeve) {
                        androidx.compose.material3.DropdownMenuItem({ Text("Rename") }, { menu = false; renaming = true })
                        if (p.tracks.size > 1) androidx.compose.material3.DropdownMenuItem({ Text("Reorder songs") }, { menu = false; reordering = true })
                        androidx.compose.material3.DropdownMenuItem({ Text("Delete playlist") }, { menu = false; deleting = true })
                    }
                }
            },
        )
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
