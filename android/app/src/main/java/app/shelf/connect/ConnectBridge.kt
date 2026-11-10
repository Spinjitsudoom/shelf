package app.shelf.connect

import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import app.shelf.data.Track
import app.shelf.playback.PlayContext
import app.shelf.playback.playContext
import app.shelf.playback.track
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull

/**
 * Connect on the phone's own player. While this phone plays, it tells the other devices what's
 * playing (on every change, and every 5 s), and runs their commands. When it's handed the music
 * (takeover) it carries on from there; when another device takes it, it stops. When the device
 * it was controlling goes away, it picks the music up here, paused, at the same place.
 *
 * [onMode] says when the controls should drive another device (true) or this phone (false).
 */
class ConnectBridge(
    private val link: RemoteLink,
    private val player: Player,
    private val toItem: (Track, PlayContext?) -> MediaItem,
    private val onVolume: (Float) -> Unit,
    private val onMode: (Boolean) -> Unit,
    private val clock: () -> Long = System::currentTimeMillis,
    private val privateSession: () -> Boolean = { false },
) : ConnectListener, Player.Listener {
    private var last: ConnectUi? = null
    private var remoteMode = false
    private var claimedFor: String? = null
    private var queueSig: String? = null
    private var rev = 0
    private var lastReport = 0L
    var userVolume = 1f
        private set

    private val active get() = link.ui.value.let { it.connected && it.activeId == it.selfId }

    fun attach() = player.addListener(this)

    private fun claim() { link.send(JsonObject(mapOf("type" to JsonPrimitive("claim")))) }

    override fun onEvents(player: Player, events: Player.Events) {
        if (events.contains(Player.EVENT_IS_PLAYING_CHANGED) && player.isPlaying) {
            val u = link.ui.value
            if (u.connected && u.activeId != u.selfId) claim()
        }
        if (active) report(forceQueue = false, periodic = false)
    }

    /** Every second from the service: a progress report every 5 s while playing here. */
    fun tick() { if (active && clock() - lastReport >= 5000) report(forceQueue = false) }

    fun report(forceQueue: Boolean, periodic: Boolean = true) {
        lastReport = clock()
        val items = (0 until player.mediaItemCount).map { player.getMediaItemAt(it) }
        val tracks = items.mapNotNull { it.track() }
        val current = player.currentMediaItem
        val t = current?.track()
        val ctx = current?.playContext()
        val dur = player.duration.takeIf { it != C.TIME_UNSET }?.div(1000.0) ?: t?.duration ?: 0.0
        val state = JsonObject(mapOf(
            "index" to JsonPrimitive(player.currentMediaItemIndex),
            "track" to (t?.let { connectJson.encodeToJsonElement(Track.serializer(), it) } ?: JsonNull),
            "playing" to JsonPrimitive(player.playWhenReady && player.playbackState != Player.STATE_ENDED),
            "position" to JsonPrimitive(player.currentPosition / 1000.0),
            "duration" to JsonPrimitive(dur),
            "shuffle" to JsonPrimitive(player.shuffleModeEnabled),
            "repeat" to JsonPrimitive(when (player.repeatMode) { Player.REPEAT_MODE_ALL -> "all"; Player.REPEAT_MODE_ONE -> "one"; else -> "off" }),
            "context" to contextJson(ctx?.let { WebContext(it.label, webHref(it.route)) }),
            "volume" to JsonPrimitive(userVolume.toDouble()),
            "private" to JsonPrimitive(privateSession()), // kept out of friend activity
        ))
        val msg = mutableMapOf<String, JsonElement>("type" to JsonPrimitive("state"), "state" to state)
        val sig = tracks.joinToString(",") { it.id.toString() }
        if (forceQueue || sig != queueSig) {
            queueSig = sig
            msg["queue"] = JsonObject(mapOf("rev" to JsonPrimitive(++rev), "tracks" to tracksJson(tracks), "original" to JsonNull))
        }
        link.send(JsonObject(msg))
    }

    override fun onConnected() {
        val u = link.ui.value
        if (player.playWhenReady && player.mediaItemCount > 0 && u.activeId != u.selfId) { claim(); claimedFor = u.activeId }
        if (active) report(forceQueue = true)
    }

    /** Connect's state changed: work out who's playing. */
    fun onUi(u: ConnectUi) {
        val old = last
        last = u
        var remote = u.remote
        // Playing here when the others think another device is (back after a dropout): say so, and keep playing.
        if (remote && player.playWhenReady && player.mediaItemCount > 0) {
            if (claimedFor != u.activeId) { claim(); claimedFor = u.activeId }
            remote = false
        }
        if (remoteMode && !remote && u.activeId != u.selfId && old != null && old.queue.isNotEmpty()) {
            // The device being controlled went away: carry on here from where it was, paused.
            val s = old.state ?: RemoteState()
            val pos = s.position + if (s.playing) (clock() - old.at) / 1000.0 else 0.0
            load(Snapshot(old.queue, s.index, pos, false, s.shuffle, s.repeat, s.context))
        }
        if (remote != remoteMode) {
            remoteMode = remote
            if (remote) player.pause()
            onMode(remote)
        }
        val playingHere = u.connected && u.activeId == u.selfId
        if (playingHere && (old == null || !(old.connected && old.activeId == old.selfId))) report(forceQueue = true)
    }

    private fun context(c: WebContext?): PlayContext? = c?.let { PlayContext(it.label, nativeRoute(it.href) ?: "") }

    private fun load(s: Snapshot) {
        if (s.queue.isEmpty()) return
        val ctx = context(s.context)
        player.setMediaItems(s.queue.map { toItem(it, ctx) }, s.index.coerceIn(0, s.queue.lastIndex), (s.position * 1000).toLong())
        player.shuffleModeEnabled = s.shuffle
        player.repeatMode = when (s.repeat) { "all" -> Player.REPEAT_MODE_ALL; "one" -> Player.REPEAT_MODE_ONE; else -> Player.REPEAT_MODE_OFF }
        player.prepare()
        player.playWhenReady = s.playing
    }

    private fun tracksOf(e: JsonElement?): List<Track> =
        runCatching { connectJson.decodeFromJsonElement(ListSerializer(Track.serializer()), e ?: JsonArray(emptyList())) }.getOrDefault(emptyList())

    private fun JsonArray.num(i: Int) = (getOrNull(i) as? JsonPrimitive)?.doubleOrNull

    override fun onCmd(name: String, args: JsonArray) {
        val p = player
        when (name) {
            "playList" -> {
                val tracks = tracksOf(args.getOrNull(0))
                if (tracks.isEmpty()) return
                val opts = args.getOrNull(2) as? JsonObject
                val ctx = context((opts?.get("context") as? JsonObject)?.let { WebContext((it["label"] as? JsonPrimitive)?.content ?: "", (it["href"] as? JsonPrimitive)?.content) })
                val start = (args.getOrNull(1) as? JsonPrimitive)?.intOrNull ?: 0
                p.setMediaItems(tracks.map { toItem(it, ctx) }, start.coerceIn(0, tracks.lastIndex), 0)
                if ((opts?.get("shuffle") as? JsonPrimitive)?.booleanOrNull == true) p.shuffleModeEnabled = true
                p.prepare(); p.play()
            }
            "playNext" -> {
                val ctx = p.currentMediaItem?.playContext()
                val items = tracksOf(args.getOrNull(0)).map { toItem(it, ctx) }
                if (p.mediaItemCount == 0) { p.setMediaItems(items); p.prepare(); p.play() } else p.addMediaItems(p.currentMediaItemIndex + 1, items)
            }
            "addToQueue" -> {
                val ctx = p.currentMediaItem?.playContext()
                val items = tracksOf(args.getOrNull(0)).map { toItem(it, ctx) }
                if (p.mediaItemCount == 0) { p.setMediaItems(items); p.prepare(); p.play() } else p.addMediaItems(items)
            }
            "jumpTo" -> args.num(0)?.toInt()?.takeIf { it in 0 until p.mediaItemCount }?.let { p.seekTo(it, 0) }
            "removeAt" -> args.num(0)?.toInt()?.takeIf { it in 0 until p.mediaItemCount }?.let { p.removeMediaItem(it) }
            "clearUpNext" -> if (p.currentMediaItemIndex + 1 < p.mediaItemCount) p.removeMediaItems(p.currentMediaItemIndex + 1, p.mediaItemCount)
            "toggle" -> if (p.playWhenReady) p.pause() else { p.prepare(); p.play() }
            "play" -> { p.prepare(); p.play() }
            "pause" -> p.pause()
            "next" -> p.seekToNext()
            "prev" -> p.seekToPrevious()
            "seek" -> args.num(0)?.let { p.seekTo((it.coerceAtLeast(0.0) * 1000).toLong()) }
            "setVolume" -> args.num(0)?.let { userVolume = it.coerceIn(0.0, 1.0).toFloat(); onVolume(userVolume); if (active) report(false) }
            "toggleShuffle" -> p.shuffleModeEnabled = !p.shuffleModeEnabled
            "cycleRepeat" -> p.repeatMode = when (p.repeatMode) { Player.REPEAT_MODE_OFF -> Player.REPEAT_MODE_ALL; Player.REPEAT_MODE_ALL -> Player.REPEAT_MODE_ONE; else -> Player.REPEAT_MODE_OFF }
        }
    }

    override fun onTakeover(snapshot: Snapshot) = load(snapshot)

    override fun onRelease() = player.pause()
}
