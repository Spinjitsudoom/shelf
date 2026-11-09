package app.shelf.playback

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.net.ConnectivityManager
import android.os.Handler
import android.os.Looper
import androidx.annotation.OptIn
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.cache.CacheDataSource
import androidx.media3.datasource.okhttp.OkHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.session.DefaultMediaNotificationProvider
import androidx.media3.session.MediaLibraryService
import androidx.media3.session.MediaSession
import androidx.media3.session.MediaSession.MediaItemsWithStartPosition
import app.shelf.MainActivity
import app.shelf.R
import app.shelf.ShelfApp
import app.shelf.data.ShelfApi
import app.shelf.data.Track
import app.shelf.connect.ConnectBridge
import app.shelf.connect.RemotePlayer
import com.google.common.util.concurrent.Futures
import com.google.common.util.concurrent.ListenableFuture
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import java.io.File

/**
 * The music: Android's media engine (ExoPlayer) in a service of its own, so it plays on with
 * the screen off, after Shelf is swiped away and through MIUI's clean-ups. Its media session
 * gives the notification, lock screen, headphone and Bluetooth buttons, and car displays.
 *
 * It plays downloads from the phone and streams the rest through the signed-in client, keeps
 * recently played songs in a cache, records plays (PlayCounter), and saves the queue (QueueStore) so it comes back where
 * it was if the app is killed, including for Bluetooth "play" after a restart.
 */
@OptIn(UnstableApi::class)
class PlaybackService : MediaLibraryService() {
    private lateinit var player: ExoPlayer
    private lateinit var session: MediaLibrarySession
    private lateinit var store: QueueStore
    private lateinit var remote: RemotePlayer
    private lateinit var bridge: ConnectBridge
    private val main = Handler(Looper.getMainLooper())
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var lastSave = 0L

    private val app get() = application as ShelfApp
    private val api: ShelfApi? get() = app.container.api
    private val downloads get() = app.container.downloads

    private val counter = PlayCounter { id ->
        val a = api ?: return@PlayCounter
        scope.launch(Dispatchers.IO) { runCatching { a.played(id) } }
    }

    /** Every second while playing: count what's heard, and save where it is every ten. */
    private val tick = object : Runnable {
        override fun run() {
            if (player.isPlaying) {
                counter.onPosition(player.currentPosition / 1000.0)
                if (System.currentTimeMillis() - lastSave > 10_000) save()
            }
            bridge.tick()
            main.postDelayed(this, 1000)
        }
    }

    override fun onCreate() {
        super.onCreate()
        store = QueueStore(File(filesDir, "queue.json"))
        val upstream = OkHttpDataSource.Factory(app.container.okHttp)
        val recent = CacheDataSource.Factory().setCache(MusicStorage.recent(this)).setUpstreamDataSourceFactory(upstream)
            .setFlags(CacheDataSource.FLAG_IGNORE_CACHE_ON_ERROR)
        // Downloads first (read only: the download manager writes them), then recently played, then the server.
        val dataSource = CacheDataSource.Factory().setCache(MusicStorage.downloads(this)).setUpstreamDataSourceFactory(recent)
            .setCacheWriteDataSinkFactory(null)
        player = ExoPlayer.Builder(this)
            .setMediaSourceFactory(DefaultMediaSourceFactory(dataSource))
            .setAudioAttributes(AudioAttributes.Builder().setUsage(C.USAGE_MEDIA).setContentType(C.AUDIO_CONTENT_TYPE_MUSIC).build(), true)
            .setHandleAudioBecomingNoisy(true) // headphones out: pause
            .setWakeMode(C.WAKE_MODE_NETWORK) // keeps the phone and Wi-Fi awake while playing
            .build()
        player.addListener(object : Player.Listener {
            override fun onMediaItemTransition(item: MediaItem?, reason: Int) {
                item?.track()?.let { counter.onTrackStarted(it.id, it.duration) }
                level(item)
                save()
            }
            override fun onIsPlayingChanged(isPlaying: Boolean) { save() }
        })
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        session = MediaLibrarySession.Builder(this, player, Callback()).setSessionActivity(open)
            .setBitmapLoader(artworkLoader(this, app.container.okHttp)).build()
        setMediaNotificationProvider(DefaultMediaNotificationProvider.Builder(this).build().apply { setSmallIcon(R.drawable.ic_stat) })
        restore(play = false)
        startConnect()
        level(player.currentMediaItem)
        scope.launch { app.container.settings.settings.collect { level(player.currentMediaItem) } }
        main.post(tick)
    }

    /**
     * Shelf Connect: this phone plays for the user's other devices (reporting and taking their
     * commands), or, while another device plays, the session's player becomes a remote for it.
     */
    private fun startConnect() {
        val connect = app.container.connect
        remote = RemotePlayer(mainLooper, connect, { api })
        bridge = ConnectBridge(connect, player, ::playableItem,
            onVolume = { level(player.currentMediaItem) },
            onMode = { isRemote -> session.player = if (isRemote) remote else player })
        bridge.attach()
        connect.listener = bridge
        connect.start()
        scope.launch { connect.ui.collect { remote.refresh(); bridge.onUi(it) } }
    }

    /** A song ready to play here (from its download, or streamed in the quality the settings choose). */
    private fun playableItem(t: Track, context: PlayContext?): MediaItem =
        api?.let { t.toMediaItem(it, qualityFor(t.codec), context, downloads.uriFor(t.id)) } ?: t.toControllerItem(null as String?, context)

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaLibrarySession = session

    /** Swiped away: keep going if music is playing; otherwise there's nothing to keep. */
    override fun onTaskRemoved(rootIntent: Intent?) {
        if (!player.playWhenReady || player.mediaItemCount == 0) stopSelf()
    }

    override fun onDestroy() {
        save()
        app.container.connect.listener = null
        app.container.connect.stop()
        remote.release()
        main.removeCallbacksAndMessages(null)
        scope.cancel()
        session.release()
        player.release()
        super.onDestroy()
    }

    private fun metered(): Boolean = (getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager).isActiveNetworkMetered

    /** The quality to stream a song in, from the settings: Wi-Fi's choice, or mobile data's ("auto": streamQuality). */
    private fun qualityFor(codec: String?): String {
        val s = app.container.settings.settings.value
        return if (!metered()) s.wifiQuality else if (s.dataQuality == "auto") streamQuality(codec, true) else s.dataQuality
    }

    /** Volume levelling: set for each song as it starts (and again when the setting changes). */
    private fun level(item: MediaItem?) {
        val s = app.container.settings.settings.value
        val t = item?.track()
        val levelled = if (s.normalize && t != null) volumeFor(gainDb(t.lufs, t.peak, s.loudness)) else 1f
        // The volume another device set for this phone (over Connect), on top of the levelling.
        player.volume = levelled * (if (::bridge.isInitialized) bridge.userVolume else 1f)
    }

    /** The playable version of items handed over by a screen (they come without a stream address). */
    private fun playable(items: List<MediaItem>): List<MediaItem> {
        val a = api ?: return emptyList()
        return items.mapNotNull { item -> item.track()?.let { t -> t.toMediaItem(a, qualityFor(t.codec), item.playContext(), downloads.uriFor(t.id)) } }
    }

    private fun save() {
        lastSave = System.currentTimeMillis()
        val items = (0 until player.mediaItemCount).mapNotNull { player.getMediaItemAt(it).track() }
        if (items.isEmpty()) return
        store.save(QueueSnapshot(items, player.currentMediaItemIndex, player.currentPosition,
            player.currentMediaItem?.playContext(), player.shuffleModeEnabled, player.repeatMode))
    }

    private fun snapshotItems(): MediaItemsWithStartPosition? {
        val s = store.load() ?: return null
        val a = api ?: return null
        if (s.tracks.isEmpty()) return null
        return MediaItemsWithStartPosition(s.tracks.map { it.toMediaItem(a, qualityFor(it.codec), s.context, downloads.uriFor(it.id)) },
            s.index.coerceIn(0, s.tracks.lastIndex), s.positionMs)
    }

    /** Back where it was, paused (or playing, for Bluetooth "play" after a restart). */
    private fun restore(play: Boolean) {
        if (player.mediaItemCount > 0) return
        val s = store.load() ?: return
        val items = snapshotItems() ?: return
        player.setMediaItems(items.mediaItems, items.startIndex, items.startPositionMs)
        player.shuffleModeEnabled = s.shuffle
        player.repeatMode = s.repeat
        player.prepare()
        player.playWhenReady = play
    }

    private inner class Callback : MediaLibrarySession.Callback {
        override fun onAddMediaItems(session: MediaSession, controller: MediaSession.ControllerInfo, mediaItems: MutableList<MediaItem>):
            ListenableFuture<MutableList<MediaItem>> = Futures.immediateFuture(playable(mediaItems).toMutableList())

        override fun onSetMediaItems(session: MediaSession, controller: MediaSession.ControllerInfo, mediaItems: MutableList<MediaItem>,
                                     startIndex: Int, startPositionMs: Long): ListenableFuture<MediaItemsWithStartPosition> =
            Futures.immediateFuture(MediaItemsWithStartPosition(playable(mediaItems), startIndex, startPositionMs))

        override fun onPlaybackResumption(session: MediaSession, controller: MediaSession.ControllerInfo, isForPlayback: Boolean):
            ListenableFuture<MediaItemsWithStartPosition> =
            snapshotItems()?.let { Futures.immediateFuture(it) } ?: Futures.immediateFailedFuture(IllegalStateException("Nothing to resume"))
    }
}
