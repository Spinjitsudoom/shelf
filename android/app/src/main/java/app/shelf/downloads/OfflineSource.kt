package app.shelf.downloads

import app.shelf.data.Album
import app.shelf.data.AlbumDetail
import app.shelf.data.ArtistSummary
import app.shelf.data.Home
import app.shelf.data.LibrarySource
import app.shelf.data.PlaylistDetail
import app.shelf.data.PlaylistSummary
import app.shelf.data.ShelfError
import app.shelf.data.Track

/**
 * The library, falling back to what's downloaded when the server can't be reached: the same
 * screens then show downloaded albums, playlists and Favourites, and play them from the phone.
 */
class OfflineSource(private val online: LibrarySource, private val index: DownloadIndex) : LibrarySource by online {
    private inline fun <T> orOffline(fallback: () -> T?, call: () -> T): T =
        try { call() } catch (e: ShelfError.Offline) { fallback() ?: throw e }

    private fun of(kind: String) = index.all().filter { it.kind == kind }

    private fun Downloadable.asAlbum() = Album(id, name, subtitle, color = color, cover = covers.firstOrNull()?.cover,
        trackCount = tracks.size, duration = tracks.sumOf { it.duration })

    override suspend fun home(): Home = orOffline({ Home(recent = of("album").map { it.asAlbum() }) }) { online.home() }
    override suspend fun mixes() = orOffline({ emptyList() }) { online.mixes() }
    override suspend fun albums(sort: String): List<Album> = orOffline({ of("album").map { it.asAlbum() } }) { online.albums(sort) }
    override suspend fun album(id: Int): AlbumDetail = orOffline({
        index.get("album", id)?.let { d -> AlbumDetail(d.id, d.name, d.subtitle, color = d.color, cover = d.covers.firstOrNull()?.cover,
            trackCount = d.tracks.size, duration = d.tracks.sumOf { it.duration }, tracks = d.tracks) }
    }) { online.album(id) }
    override suspend fun artists(): List<ArtistSummary> = orOffline({
        of("album").groupBy { it.subtitle }.map { (name, albums) -> ArtistSummary(name, albums.size, albums.sumOf { it.tracks.size }, albums.first().id, albums.first().covers.firstOrNull()?.cover) }
    }) { online.artists() }
    override suspend fun playlists(): List<PlaylistSummary> = orOffline({
        of("playlist").map { PlaylistSummary(it.id, it.name, it.subtitle.ifBlank { null }, it.tracks.size, it.tracks.sumOf { t -> t.duration }, it.covers) }
    }) { online.playlists() }
    override suspend fun playlist(id: Int): PlaylistDetail = orOffline({
        index.get("playlist", id)?.let { d -> PlaylistDetail(d.id, d.name, d.subtitle.ifBlank { null }, d.tracks.size, d.tracks.sumOf { it.duration }, d.covers, false, d.tracks) }
    }) { online.playlist(id) }
    override suspend fun likes(): List<Track> = orOffline({ index.get("favourites", 0)?.tracks }) { online.likes() }
}
