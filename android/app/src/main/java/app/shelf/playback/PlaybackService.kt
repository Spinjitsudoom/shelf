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
import app.shelf.NowPlayingWidget
import app.shelf.WidgetState
import coil3.toBitmap
import app.shelf.data.ShelfApi
import app.shelf.data.Track
import app.shelf.connect.ConnectBridge
import app.shelf.connect.RemotePlayer
import com.google.common.util.concurrent.Futures
import com.google.common.util.concurrent.ListenableFuture
import com.google.common.util.concurrent.SettableFuture
import com.google.common.collect.ImmutableList
import androidx.media3.session.LibraryResult
import androidx.media3.session.MediaLibraryService.LibraryParams
import androidx.media3.session.SessionError
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
    private lateinit var decks: Decks
    /** The player that's playing: with crossfades and Mix, whichever of the two decks has the music. */
    private val player: ExoPlayer get() = decks.current
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

    private val private get() = app.container.settings.settings.value.privateSession
    private val counter = PlayCounter { id ->
        val a = api ?: return@PlayCounter
        if (private) return@PlayCounter // a private session leaves no history (as on the web)
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

    /** Crossfades and Mix transitions move along every 50 ms (only while this phone plays, not as a remote). */
    private val transitions = object : Runnable {
        override fun run() {
            if (session.player !== remote) decks.tick(android.os.SystemClock.elapsedRealtime())
            main.postDelayed(this, 50)
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
        // Two decks, so songs can crossfade and Mix; each has its own equalizer, balance and mono on the way to the speaker.
        val attrs = AudioAttributes.Builder().setUsage(C.USAGE_MEDIA).setContentType(C.AUDIO_CONTENT_TYPE_MUSIC).build()
        fun deck(sound: ShelfAudioProcessor, focus: Boolean): ExoPlayer {
            val renderers = object : androidx.media3.exoplayer.DefaultRenderersFactory(this) {
                override fun buildAudioSink(context: Context, enableFloatOutput: Boolean, enableAudioTrackPlaybackParams: Boolean): androidx.media3.exoplayer.audio.AudioSink =
                    androidx.media3.exoplayer.audio.DefaultAudioSink.Builder(context).setAudioProcessors(arrayOf(sound))
                        .setEnableFloatOutput(enableFloatOutput).setEnableAudioTrackPlaybackParams(enableAudioTrackPlaybackParams).build()
            }
            return ExoPlayer.Builder(this, renderers)
                .setMediaSourceFactory(DefaultMediaSourceFactory(dataSource))
                .setAudioAttributes(attrs, focus) // only the deck that plays for the person holds audio focus
                .setHandleAudioBecomingNoisy(true) // headphones out: pause
                .setWakeMode(C.WAKE_MODE_NETWORK) // keeps the phone and Wi-Fi awake while playing
                .build()
        }
        deckA = deck(soundA, focus = true)
        deckB = deck(soundB, focus = false)
        decks = Decks(deckA, deckB, effects = { if (it === deckA) soundA else soundB }, planFor = ::transitionFor, baseVolume = ::baseVolume)
        decks.onSwap = ::onSwap
        decks.addListener(object : Player.Listener {
            override fun onMediaItemTransition(item: MediaItem?, reason: Int) {
                // Skipped to another song (next, previous, a tap in the queue) early on: a skip.
                if (reason == Player.MEDIA_ITEM_TRANSITION_REASON_SEEK && !private) counter.skipped()?.let { id ->
                    api?.let { a -> scope.launch(Dispatchers.IO) { runCatching { a.skipped(id) } } }
                }
                autoplayIfLast()
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
        scope.launch { app.container.settings.settings.collect { s -> level(player.currentMediaItem); applySound(s); app.container.connect.rename(s.deviceName) } }
        startSleepTimer()
        main.post(tick)
        main.post(transitions)
    }

    /**
     * Shelf Connect: this phone plays for the user's other devices (reporting and taking their
     * commands), or, while another device plays, the session's player becomes a remote for it.
     */
    private fun startConnect() {
        val connect = app.container.connect
        remote = RemotePlayer(mainLooper, connect, { api })
        bridge = ConnectBridge(connect, { decks.current }, ::playableItem,
            onVolume = { level(player.currentMediaItem) },
            onMode = { isRemote -> session.player = if (isRemote) remote else player; pushWidget() },
            privateSession = { app.container.settings.settings.value.privateSession })
        decks.addListener(bridge)
        val widget = object : Player.Listener {
            override fun onEvents(p: Player, events: Player.Events) { if (p === session.player) pushWidget() }
        }
        decks.addListener(widget)
        remote.addListener(widget)
        connect.listener = bridge
        connect.start()
        scope.launch { connect.ui.collect { remote.refresh(); bridge.onUi(it) } }
    }

    private var widgetArtFor: String? = null
    private var widgetArt: android.graphics.Bitmap? = null

    /** The home-screen widget: what's playing (here or on the device being controlled), and its cover. */
    private fun pushWidget() {
        val p = session.player
        val t = p.currentMediaItem?.track()
        val device = if (p === remote) app.container.connect.ui.value.activeDevice?.name?.ifBlank { "Web browser" } else null
        val state = t?.let { WidgetState(it, p.playWhenReady && p.playbackState != Player.STATE_ENDED, device) }
        val url = t?.let { api?.coverUrl(it.albumId, it.cover, 160) }
        if (url != widgetArtFor) {
            widgetArtFor = url
            widgetArt = null
            if (url != null) scope.launch {
                val result = coil3.SingletonImageLoader.get(this@PlaybackService)
                    .execute(coil3.request.ImageRequest.Builder(this@PlaybackService).data(url).size(160).build())
                val bmp = (result as? coil3.request.SuccessResult)?.image?.toBitmap()
                if (widgetArtFor == url && bmp != null) { widgetArt = bmp; pushWidget() }
            }
        }
        NowPlayingWidget.push(this, state, widgetArt)
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
        NowPlayingWidget.push(this, null, null)
        main.removeCallbacksAndMessages(null)
        scope.cancel()
        session.release()
        deckA.release()
        deckB.release()
        super.onDestroy()
    }

    private fun metered(): Boolean = (getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager).isActiveNetworkMetered

    /** The quality to stream a song in, from the settings: Wi-Fi's choice, or mobile data's ("auto": streamQuality). */
    private fun qualityFor(codec: String?): String {
        val s = app.container.settings.settings.value
        val q = if (!metered()) s.wifiQuality else if (s.dataQuality == "auto") streamQuality(codec, true) else s.dataQuality
        return playableQuality(codec, q, Decoders::has)
    }

    private var autoplaying = false

    /** The last song has started: add similar ones, so the music carries on (unless repeat is on, or it's off in Settings). */
    private fun autoplayIfLast() {
        val seed = player.currentMediaItem?.track() ?: return
        if (autoplaying || !app.container.settings.settings.value.autoplay || player.currentMediaItemIndex != player.mediaItemCount - 1) return
        val a = api ?: return
        autoplaying = true
        val context = player.currentMediaItem?.playContext()
        scope.launch {
            val similar = try { kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) { a.similar(seed.id) } } catch (e: Exception) { emptyList() } // offline: just stop at the end
            val ids = (0 until player.mediaItemCount).mapNotNull { player.getMediaItemAt(it).track()?.id }
            val fresh = autoplayPick(ids, similar, player.repeatMode == Player.REPEAT_MODE_OFF)
            if (fresh.isNotEmpty() && player.currentMediaItem?.track()?.id == seed.id && player.currentMediaItemIndex == player.mediaItemCount - 1)
                player.addMediaItems(fresh.map { playableItem(it, context) })
            autoplaying = false
        }
    }

    private val soundA = ShelfAudioProcessor()
    private val soundB = ShelfAudioProcessor()
    private lateinit var deckA: ExoPlayer
    private lateinit var deckB: ExoPlayer

    /** How the playing song hands over to the next: the Mix playlist's transition, the crossfade setting, or not at all (gapless). */
    private fun transitionFor(cur: Track, nxt: Track, durationS: Double, deck: Player): Plan? {
        if (session.player === remote) return null
        val s = app.container.settings.settings.value
        val mix = deck.currentMediaItem?.playContext()?.mix == true && deck.repeatMode != Player.REPEAT_MODE_ONE
        return if (mix) plan(cur, nxt, cur.transition, durationS)
        else crossfadePlan(s.crossfade, s.crossfadeAlbums, deck.shuffleModeEnabled, cur, nxt, durationS)
    }

    /** The music moved to the other deck at the end of a transition: everything follows it. */
    private fun onSwap(deck: ExoPlayer) {
        if (session.player !== remote) session.player = deck
        deck.pauseAtEndOfMediaItems = app.container.sleep.state.value?.endOfSong == true
        (if (deck === deckA) deckB else deckA).pauseAtEndOfMediaItems = false
        deck.currentMediaItem?.track()?.let { counter.onTrackStarted(it.id, it.duration) }
        autoplayIfLast()
        save()
        pushWidget()
        bridge.onDeckChanged()
    }
    private var sleepFade = 1f

    /** The sleep timer: fades this phone's music over its last seconds, then pauses whatever is playing (here, or the device being controlled). */
    private fun startSleepTimer() {
        val sleep = app.container.sleep
        sleep.onStop = { session.player.pause(); sleepFade = 1f; level(player.currentMediaItem) }
        val fade = object : Runnable {
            override fun run() {
                val f = sleep.onTick()
                if (f != sleepFade) { sleepFade = f; level(player.currentMediaItem) }
                if (sleep.state.value?.endsAt != null) main.postDelayed(this, 200)
            }
        }
        scope.launch {
            sleep.state.collect { s ->
                main.removeCallbacks(fade)
                if (s?.endsAt != null) main.post(fade) else if (sleepFade != 1f) { sleepFade = 1f; level(player.currentMediaItem) }
                // "End of this song": the player pauses when the song reaches its end.
                player.pauseAtEndOfMediaItems = s?.endOfSong == true
            }
        }
        decks.addListener(object : Player.Listener {
            override fun onPlayWhenReadyChanged(playWhenReady: Boolean, reason: Int) {
                if (!playWhenReady && reason == Player.PLAY_WHEN_READY_CHANGE_REASON_END_OF_MEDIA_ITEM) sleep.onSongEnded()
            }
        })
    }

    private fun applySound(s: app.shelf.settings.Settings) {
        for (sound in listOf(soundA, soundB)) sound.setup(if (s.eqEnabled) s.eqGains else null, s.balance, s.mono)
    }

    /** Volume levelling: set for each song as it starts (and again when the setting changes); the decks apply it (with any transition). */
    @Suppress("UNUSED_PARAMETER")
    private fun level(item: MediaItem?) { if (::decks.isInitialized) decks.applyVolumes() }

    /** A deck's volume before any transition: its song's levelling, the volume another device set (over Connect), the sleep timer's fade. */
    private fun baseVolume(deck: Player): Float {
        val s = app.container.settings.settings.value
        val t = deck.currentMediaItem?.track()
        val levelled = if (s.normalize && t != null) volumeFor(gainDb(t.lufs, t.peak, s.loudness)) else 1f
        return levelled * sleepFade * (if (::bridge.isInitialized) bridge.userVolume else 1f)
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

    private val tree = LibraryTree { api }

    /** Run [block] off the main thread's way and hand its answer to Media3 as a future. */
    private fun <T> later(fallback: T, block: suspend () -> T): ListenableFuture<T> {
        val f = SettableFuture.create<T>()
        scope.launch { f.set(try { block() } catch (e: Exception) { if (e is kotlinx.coroutines.CancellationException) throw e; fallback }) }
        return f
    }

    /** Items from a car display come as ids only ("album:5|12"): look the songs up. */
    private suspend fun resolve(items: List<MediaItem>): List<MediaItem> = items.flatMap { item ->
        if (item.track() != null) listOf(item)
        else tree.expand(item.mediaId)?.let { (list, i) -> listOf(list[i]) }.orEmpty()
    }

    private inner class Callback : MediaLibrarySession.Callback {
        override fun onAddMediaItems(session: MediaSession, controller: MediaSession.ControllerInfo, mediaItems: MutableList<MediaItem>):
            ListenableFuture<MutableList<MediaItem>> =
            if (mediaItems.all { it.track() != null }) Futures.immediateFuture(playable(mediaItems).toMutableList())
            else later(mutableListOf()) { playable(resolve(mediaItems)).toMutableList() }

        override fun onSetMediaItems(session: MediaSession, controller: MediaSession.ControllerInfo, mediaItems: MutableList<MediaItem>,
                                     startIndex: Int, startPositionMs: Long): ListenableFuture<MediaItemsWithStartPosition> {
            // One song picked in the car: play its whole list from there.
            val single = mediaItems.singleOrNull()
            if (single != null && '|' in single.mediaId) return later(MediaItemsWithStartPosition(emptyList(), 0, 0)) {
                tree.expand(single.mediaId)?.let { (list, i) -> MediaItemsWithStartPosition(playable(list), i, 0) }
                    ?: MediaItemsWithStartPosition(playable(resolve(mediaItems)), 0, 0)
            }
            return Futures.immediateFuture(MediaItemsWithStartPosition(playable(mediaItems), startIndex, startPositionMs))
        }

        override fun onGetLibraryRoot(session: MediaLibrarySession, browser: MediaSession.ControllerInfo, params: LibraryParams?):
            ListenableFuture<LibraryResult<MediaItem>> = Futures.immediateFuture(LibraryResult.ofItem(tree.root(), params))

        override fun onGetChildren(session: MediaLibrarySession, browser: MediaSession.ControllerInfo, parentId: String, page: Int, pageSize: Int,
                                   params: LibraryParams?): ListenableFuture<LibraryResult<ImmutableList<MediaItem>>> =
            later(LibraryResult.ofError(SessionError.ERROR_IO)) {
                val all = tree.children(parentId)
                val from = (page * pageSize).coerceIn(0, all.size)
                LibraryResult.ofItemList(all.subList(from, (from + pageSize).coerceAtMost(all.size)), params)
            }

        override fun onGetItem(session: MediaLibrarySession, browser: MediaSession.ControllerInfo, mediaId: String):
            ListenableFuture<LibraryResult<MediaItem>> = later(LibraryResult.ofError(SessionError.ERROR_BAD_VALUE)) {
                tree.expand(mediaId)?.let { (list, i) -> LibraryResult.ofItem(list[i], null) } ?: LibraryResult.ofError(SessionError.ERROR_BAD_VALUE)
            }

        override fun onPlaybackResumption(session: MediaSession, controller: MediaSession.ControllerInfo, isForPlayback: Boolean):
            ListenableFuture<MediaItemsWithStartPosition> =
            snapshotItems()?.let { Futures.immediateFuture(it) } ?: Futures.immediateFailedFuture(IllegalStateException("Nothing to resume"))
    }
}
