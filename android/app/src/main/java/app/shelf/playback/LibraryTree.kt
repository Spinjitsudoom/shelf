package app.shelf.playback

import androidx.core.net.toUri
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import app.shelf.data.LibrarySource
import app.shelf.data.Track

/**
 * What a car display (Android Auto) can browse: Home, Mixes, Playlists, Albums and Favourites,
 * then the songs in each. A song's id names the list it's in ("album:5|12"), so playing it
 * queues the whole list from that song, as tapping a song in the app does.
 */
class LibraryTree(private val source: () -> LibrarySource?) {
    companion object {
        const val ROOT = "root"
        private val SECTIONS = listOf("home" to "Home", "mixes" to "Mixes", "playlists" to "Playlists", "albums" to "Albums", "favourites" to "Favourites")
    }

    fun root(): MediaItem = folder(ROOT, "Shelf", null, MediaMetadata.MEDIA_TYPE_FOLDER_MIXED)

    private fun folder(id: String, title: String, subtitle: String?, type: Int, art: String? = null) = MediaItem.Builder().setMediaId(id)
        .setMediaMetadata(MediaMetadata.Builder().setTitle(title).setSubtitle(subtitle).setArtworkUri(art?.toUri())
            .setIsBrowsable(true).setIsPlayable(false).setMediaType(type).build()).build()

    /** The songs in a list, and what "Playing from" says for them. */
    private suspend fun tracksOf(parentId: String): Pair<List<Track>, PlayContext>? {
        val src = source() ?: return null
        val (kind, key) = parentId.substringBefore(':') to parentId.substringAfter(':', "")
        return when (kind) {
            "album" -> src.album(key.toInt()).let { it.tracks to PlayContext(it.title, "album/${it.id}") }
            "playlist" -> src.playlist(key.toInt()).let { it.tracks to PlayContext(it.name, "playlist/${it.id}") }
            "mix" -> src.mix(key).let { it.tracks to PlayContext(it.name, "mix/${android.net.Uri.encode(key)}") }
            "favourites" -> src.likes() to PlayContext("Favourites", "favourites")
            else -> null
        }
    }

    suspend fun children(parentId: String): List<MediaItem> {
        val src = source() ?: return emptyList()
        return when (parentId) {
            ROOT -> SECTIONS.map { (id, title) -> folder(id, title, null, MediaMetadata.MEDIA_TYPE_FOLDER_MIXED) }
            "home" -> src.home().let { h -> (h.recent + h.added).distinctBy { it.id } }
                .map { folder("album:${it.id}", it.title, it.artist, MediaMetadata.MEDIA_TYPE_ALBUM, src.coverUrl(it.id, it.cover, 320)) }
            "mixes" -> src.mixes().map { folder("mix:${it.key}", it.name, it.description, MediaMetadata.MEDIA_TYPE_PLAYLIST) }
            "playlists" -> src.playlists().map { p ->
                folder("playlist:${p.id}", p.name, null, MediaMetadata.MEDIA_TYPE_PLAYLIST, p.covers.firstOrNull()?.let { src.coverUrl(it.albumId, it.cover, 320) })
            }
            "albums" -> src.albums("recent").map { folder("album:${it.id}", it.title, it.artist, MediaMetadata.MEDIA_TYPE_ALBUM, src.coverUrl(it.id, it.cover, 320)) }
            else -> tracksOf(parentId)?.let { (tracks, ctx) ->
                tracks.map { t -> t.toControllerItem(src, ctx).buildUpon().setMediaId("$parentId|${t.id}").build() }
            }.orEmpty()
        }
    }

    /** A song picked in the car: its whole list, and where in it to start (null if it's gone). */
    suspend fun expand(mediaId: String): Pair<List<MediaItem>, Int>? {
        if ('|' !in mediaId) return null
        val items = children(mediaId.substringBefore('|'))
        val index = items.indexOfFirst { it.mediaId == mediaId }
        return if (index < 0) null else items to index
    }
}
