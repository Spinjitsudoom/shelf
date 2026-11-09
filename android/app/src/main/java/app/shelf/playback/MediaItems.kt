package app.shelf.playback

import android.os.Bundle
import androidx.core.net.toUri
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import app.shelf.data.LibrarySource
import app.shelf.data.ShelfApi
import app.shelf.data.Track
import kotlinx.serialization.json.Json

private val json = Json { ignoreUnknownKeys = true }
private const val TRACK = "shelf.track"
private const val CONTEXT = "shelf.context"

/** A song as the player plays it: streamed from the server, with what the notification and
 * lock screen show, and the song itself and where it was played from carried along. */
fun Track.toMediaItem(api: ShelfApi, quality: String, context: PlayContext?): MediaItem =
    toControllerItem(api, context).buildUpon().setUri(api.streamUrl(id, quality)).build()

/** The same item without its stream address (what a screen hands the player service, which
 * adds the address itself). */
fun Track.toControllerItem(source: LibrarySource, context: PlayContext?): MediaItem {
    val extras = Bundle().apply {
        putString(TRACK, json.encodeToString(Track.serializer(), this@toControllerItem))
        context?.let { putString(CONTEXT, json.encodeToString(PlayContext.serializer(), it)) }
    }
    val meta = MediaMetadata.Builder()
        .setTitle(title).setArtist(artist).setAlbumTitle(album).setAlbumArtist(albumArtist)
        .setArtworkUri(source.coverUrl(albumId, cover, 512)?.toUri())
        .setDurationMs((duration * 1000).toLong())
        .setTrackNumber(trackNo).setDiscNumber(discNo)
        .setIsPlayable(true).setIsBrowsable(false).setMediaType(MediaMetadata.MEDIA_TYPE_MUSIC)
        .setExtras(extras)
        .build()
    return MediaItem.Builder().setMediaId(id.toString()).setMediaMetadata(meta).build()
}

fun MediaItem.track(): Track? = mediaMetadata.extras?.getString(TRACK)?.let { runCatching { json.decodeFromString(Track.serializer(), it) }.getOrNull() }

fun MediaItem.playContext(): PlayContext? =
    mediaMetadata.extras?.getString(CONTEXT)?.let { runCatching { json.decodeFromString(PlayContext.serializer(), it) }.getOrNull() }
