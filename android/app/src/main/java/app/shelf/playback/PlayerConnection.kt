package app.shelf.playback

import android.content.ComponentName
import android.content.Context
import android.os.Handler
import android.os.Looper
import androidx.core.content.ContextCompat
import androidx.media3.common.Player
import androidx.media3.session.MediaController
import androidx.media3.session.SessionToken
import app.shelf.data.LibrarySource
import app.shelf.data.Track
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/** What the screens show about the music. */
data class PlayerUi(
    val current: Track? = null, val previous: Track? = null, val next: Track? = null,
    val playing: Boolean = false, val positionMs: Long = 0, val durationMs: Long = 0,
    val queue: List<Track> = emptyList(), val index: Int = -1, val context: PlayContext? = null,
    val shuffle: Boolean = false, val repeat: Int = Player.REPEAT_MODE_OFF,
)

/** The screens' line to the player service: its state as a flow, and the buttons. */
class PlayerConnection(context: Context, private val source: () -> LibrarySource?) {
    private val _state = MutableStateFlow(PlayerUi())
    val state: StateFlow<PlayerUi> = _state
    private var controller: MediaController? = null
    private val main = Handler(Looper.getMainLooper())

    private val listener = object : Player.Listener {
        override fun onEvents(player: Player, events: Player.Events) = refresh()
    }

    /** While playing, the position moves on; this keeps the scrubber and mini player's line current. */
    private val tick = object : Runnable {
        override fun run() {
            controller?.let { if (it.isPlaying) _state.value = _state.value.copy(positionMs = it.currentPosition, durationMs = it.duration.coerceAtLeast(0)) }
            main.postDelayed(this, 500)
        }
    }

    init {
        val token = SessionToken(context, ComponentName(context, PlaybackService::class.java))
        val future = MediaController.Builder(context, token).buildAsync()
        future.addListener({
            runCatching { future.get() }.getOrNull()?.let { c ->
                controller = c
                c.addListener(listener)
                refresh()
                main.post(tick)
            }
        }, ContextCompat.getMainExecutor(context))
    }

    private fun refresh() {
        val c = controller ?: return
        val queue = (0 until c.mediaItemCount).mapNotNull { c.getMediaItemAt(it).track() }
        val i = c.currentMediaItemIndex
        _state.value = PlayerUi(
            current = c.currentMediaItem?.track(),
            previous = if (c.hasPreviousMediaItem()) c.getMediaItemAt(c.previousMediaItemIndex).track() else null,
            next = if (c.hasNextMediaItem()) c.getMediaItemAt(c.nextMediaItemIndex).track() else null,
            playing = c.playWhenReady && c.playbackState != Player.STATE_ENDED,
            positionMs = c.currentPosition, durationMs = c.duration.coerceAtLeast(0),
            queue = queue, index = i, context = c.currentMediaItem?.playContext(),
            shuffle = c.shuffleModeEnabled, repeat = c.repeatMode,
        )
    }

    fun play(tracks: List<Track>, index: Int, context: PlayContext) {
        val c = controller ?: return
        val src = source() ?: return
        c.setMediaItems(tracks.map { it.toControllerItem(src, context) }, index, 0)
        c.prepare()
        c.play()
    }

    /** Right after the song that's playing. */
    fun playNext(tracks: List<Track>) {
        val c = controller ?: return
        val src = source() ?: return
        val items = tracks.map { it.toControllerItem(src, null) }
        if (c.mediaItemCount == 0) { c.setMediaItems(items); c.prepare(); c.play() } else c.addMediaItems(c.currentMediaItemIndex + 1, items)
    }

    /** At the end of the queue. */
    fun addToQueue(tracks: List<Track>) {
        val c = controller ?: return
        val src = source() ?: return
        val items = tracks.map { it.toControllerItem(src, null) }
        if (c.mediaItemCount == 0) { c.setMediaItems(items); c.prepare(); c.play() } else c.addMediaItems(items)
    }

    /**
     * A song's Mix transition changed (in a playlist that may be playing): the queue's copy follows, so the next
     * handover uses it. Not while controlling another device (that device's queue is its own).
     */
    fun updateTransition(entryId: Int, transition: kotlinx.serialization.json.JsonElement) {
        val c = controller ?: return
        val src = source() ?: return
        if (c.deviceInfo.playbackType == androidx.media3.common.DeviceInfo.PLAYBACK_TYPE_REMOTE) return
        for (i in 0 until c.mediaItemCount) {
            val item = c.getMediaItemAt(i)
            val t = item.track() ?: continue
            if (t.entryId == entryId) c.replaceMediaItem(i, t.copy(transition = transition).toControllerItem(src, item.playContext()))
        }
    }

    fun toggle() { controller?.let { if (it.playWhenReady) it.pause() else { if (it.playbackState == Player.STATE_IDLE) it.prepare(); it.play() } } }
    fun next() { controller?.seekToNextMediaItem() }
    /** Back to the start of the song, or the song before when near its start (like every player). */
    fun previous() { controller?.seekToPrevious() }
    fun seekTo(ms: Long) { controller?.seekTo(ms) }
    fun skipTo(index: Int) { controller?.let { it.seekTo(index, 0); it.play() } }
    fun toggleShuffle() { controller?.let { it.shuffleModeEnabled = !it.shuffleModeEnabled } }
    fun cycleRepeat() { controller?.let { it.repeatMode = when (it.repeatMode) { Player.REPEAT_MODE_OFF -> Player.REPEAT_MODE_ALL; Player.REPEAT_MODE_ALL -> Player.REPEAT_MODE_ONE; else -> Player.REPEAT_MODE_OFF } } }

    fun release() {
        main.removeCallbacksAndMessages(null)
        controller?.release()
        controller = null
    }
}
