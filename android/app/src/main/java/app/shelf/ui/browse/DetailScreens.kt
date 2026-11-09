package app.shelf.ui.browse

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
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
        )
    }
}

@Composable
fun PlaylistScreen(id: Int, source: LibrarySource, onPlay: OnPlay, onBack: () -> Unit, signedOut: SignedOutHandler) {
    val (state, retry) = rememberLoad(id) { source.playlist(id) }
    LoadContent(state, retry, signedOut) { p ->
        val color = albumColor(null, p.name)
        val ctx = PlayContext(p.name, Routes.playlist(p.id))
        TrackListPage(
            color = color, kind = "Playlist", title = p.name,
            cover = { MosaicCover(p.covers.mapNotNull { source.coverUrl(it.albumId, it.cover, 320) }, p.name, color) },
            byline = p.description?.takeIf { it.isNotBlank() }?.let { { Text(it, style = MaterialTheme.typography.bodyMedium, color = Shelf.colors.ink2) } },
            facts = facts(plural(p.tracks.size, "song"), fmtLength(p.tracks.sumOf { it.duration })),
            tracks = p.tracks, numbered = false, coverUrl = { source.cover(it) },
            onTrack = { onPlay(p.tracks, it, ctx) }, onShuffle = { onPlay(p.tracks.shuffled(), 0, ctx) }, onBack = onBack,
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
        )
    }
}
