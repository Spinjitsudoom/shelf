package app.shelf.downloads

import android.app.Notification
import android.content.Context
import android.os.Handler
import android.os.Looper
import androidx.annotation.OptIn
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.core.net.toUri
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.okhttp.OkHttpDataSource
import androidx.media3.exoplayer.offline.Download
import androidx.media3.exoplayer.offline.DownloadManager
import androidx.media3.exoplayer.offline.DownloadNotificationHelper
import androidx.media3.exoplayer.offline.DownloadRequest
import androidx.media3.exoplayer.offline.DownloadService
import androidx.media3.exoplayer.scheduler.Scheduler
import app.shelf.R
import app.shelf.ShelfApp
import app.shelf.data.ShelfApi
import app.shelf.playback.Decoders
import app.shelf.playback.MusicStorage
import app.shelf.playback.playableQuality
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import okhttp3.OkHttpClient
import java.io.File
import java.util.concurrent.Executors

/**
 * Downloads: albums, playlists and Favourites kept on the phone to play with no connection.
 * Media3's DownloadManager fetches each song (through the signed-in client, in the quality set
 * for Wi-Fi) into the downloads store; [index] remembers which collections were downloaded.
 */
@OptIn(UnstableApi::class)
class Downloads(private val context: Context, okHttp: OkHttpClient, private val api: () -> ShelfApi?, private val quality: () -> String) {
    val index = DownloadIndex(File(context.filesDir, "downloads.json"))
    val manager = DownloadManager(context, MusicStorage.database(context), MusicStorage.downloads(context),
        OkHttpDataSource.Factory(okHttp), Executors.newFixedThreadPool(2)).apply { maxParallelDownloads = 2 }

    private val main = Handler(Looper.getMainLooper())
    private var states = emptyMap<Int, Int>()
    private var percents = emptyMap<Int, Float>()
    private var uris = emptyMap<Int, String>()

    private val _items = MutableStateFlow(index.all())
    /** What's downloaded (or on its way). */
    val items: StateFlow<List<Downloadable>> = _items

    private val _progress = MutableStateFlow<Map<String, Float>>(emptyMap())
    /** How far along each collection is (by its key), 0..1; 1 only when every song has finished. */
    val progress: StateFlow<Map<String, Float>> = _progress

    private val poll = object : Runnable {
        override fun run() {
            if (states.values.any { it == Download.STATE_DOWNLOADING }) {
                percents = manager.currentDownloads.associate { it.request.id.toInt() to it.percentDownloaded }
                publish()
                main.postDelayed(this, 700)
            }
        }
    }

    init {
        manager.downloadIndex.getDownloads().use { c -> while (c.moveToNext()) remember(c.download) }
        publish()
        manager.addListener(object : DownloadManager.Listener {
            override fun onDownloadChanged(m: DownloadManager, download: Download, finalException: Exception?) {
                remember(download); publish()
                main.removeCallbacks(poll); main.post(poll)
            }
            override fun onDownloadRemoved(m: DownloadManager, download: Download) {
                val id = download.request.id.toIntOrNull() ?: return
                states = states - id; uris = uris - id; percents = percents - id; publish()
                if (id in refetching) {
                    refetching = refetching - id
                    if (refetching.isEmpty()) index.all().forEach { download(it) } // fetches what's missing now
                }
            }
        })
    }

    private var refetching = emptySet<Int>()

    /**
     * Downloads saved in another quality than the setting's (converted copies, before Original was
     * the default) are deleted and fetched again as it says.
     */
    fun refetchOtherQuality() {
        val q = quality()
        val codecs = index.all().flatMap { it.tracks }.associate { it.id to it.codec }
        refetching = toRefetch(uris) { id -> playableQuality(codecs[id], q, Decoders::has) }
        refetching.forEach { DownloadService.sendRemoveDownload(context, ShelfDownloadService::class.java, it.toString(), false) }
    }

    private fun remember(d: Download) {
        val id = d.request.id.toIntOrNull() ?: return
        states = states + (id to d.state)
        percents = percents + (id to d.percentDownloaded)
        uris = if (d.state == Download.STATE_COMPLETED) uris + (id to d.request.uri.toString()) else uris - id
    }

    private fun publish() {
        _items.value = index.all()
        _progress.value = index.all().associate { it.key to progressOf(it, states, percents) }
    }

    /** The address a downloaded song was fetched with (the player then plays it from the phone), or null. */
    fun uriFor(trackId: Int): String? = uris[trackId]

    fun isComplete(item: Downloadable) = isComplete(item, states)

    /** Download a collection (again, if it changed: new songs are fetched, songs taken out are deleted). */
    fun download(item: Downloadable) {
        val a = api() ?: return
        val gone = index.get(item.kind, item.id)?.let { old -> index.tracksOnlyIn(item.kind, item.id) - item.tracks.map { it.id }.toSet() }.orEmpty()
        index.add(item)
        val q = quality()
        item.tracks.filter { states[it.id] != Download.STATE_COMPLETED }.forEach { t ->
            DownloadService.sendAddDownload(context, ShelfDownloadService::class.java,
                DownloadRequest.Builder(t.id.toString(), a.streamUrl(t.id, playableQuality(t.codec, q, Decoders::has)).toUri()).build(), false)
        }
        gone.forEach { DownloadService.sendRemoveDownload(context, ShelfDownloadService::class.java, it.toString(), false) }
        publish()
    }

    /** Keep a downloaded collection in step with the server's (songs added or taken out), and try songs that failed again. */
    fun sync(item: Downloadable) { if (needsFetch(index.get(item.kind, item.id), item, states)) download(item) }

    /** Delete a collection's download (keeping songs another downloaded collection has). */
    fun remove(kind: String, id: Int) {
        val gone = index.tracksOnlyIn(kind, id)
        index.remove(kind, id)
        gone.forEach { DownloadService.sendRemoveDownload(context, ShelfDownloadService::class.java, it.toString(), false) }
        publish()
    }
}

/** Screens reach the downloads through this (null in previews and tests). */
val LocalDownloads = staticCompositionLocalOf<Downloads?> { null }

private const val CHANNEL = "downloads"

/** Keeps downloads going with the app in the background, with a progress notification. */
@OptIn(UnstableApi::class)
class ShelfDownloadService : DownloadService(2, DEFAULT_FOREGROUND_NOTIFICATION_UPDATE_INTERVAL, CHANNEL, R.string.downloads_channel, 0) {
    override fun getDownloadManager(): DownloadManager = (application as ShelfApp).container.downloads.manager
    override fun getScheduler(): Scheduler? = null
    override fun getForegroundNotification(downloads: MutableList<Download>, notMetRequirements: Int): Notification =
        DownloadNotificationHelper(this, CHANNEL).buildProgressNotification(this, R.drawable.ic_stat, null,
            if (downloads.size == 1) "Downloading 1 song" else "Downloading ${downloads.size} songs", downloads, notMetRequirements)
}
