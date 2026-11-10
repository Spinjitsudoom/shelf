package app.shelf.connect

import android.os.Looper
import androidx.annotation.OptIn
import androidx.media3.common.C
import androidx.media3.common.DeviceInfo as MediaDeviceInfo
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.common.SimpleBasePlayer
import androidx.media3.common.util.UnstableApi
import app.shelf.data.LibrarySource
import app.shelf.data.moveItem
import app.shelf.playback.PlayContext
import app.shelf.playback.queueMove
import app.shelf.playback.playContext
import app.shelf.playback.toControllerItem
import app.shelf.playback.track
import com.google.common.util.concurrent.Futures
import com.google.common.util.concurrent.ListenableFuture
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlin.math.roundToInt

private val REMOTE_DEVICE = MediaDeviceInfo.Builder(MediaDeviceInfo.PLAYBACK_TYPE_REMOTE).setMinVolume(0).setMaxVolume(100).build()
private val REPEATS = listOf("off", "all", "one")

/**
 * The player while another device plays: it shows that device's song, queue and progress (as
 * Connect reports them), and every control here (the app's buttons, the notification, the lock
 * screen, Bluetooth, the volume keys, the widget, the car) is sent to that device instead.
 */
@OptIn(UnstableApi::class)
class RemotePlayer(
    looper: Looper,
    private val link: RemoteLink,
    private val source: () -> LibrarySource?,
    private val clock: () -> Long = System::currentTimeMillis,
) : SimpleBasePlayer(looper) {

    /** Connect's state changed: show it. */
    fun refresh() = invalidateState()

    private val commands = Player.Commands.Builder().addAll(
        COMMAND_PLAY_PAUSE, COMMAND_PREPARE, COMMAND_STOP, COMMAND_RELEASE,
        COMMAND_SEEK_IN_CURRENT_MEDIA_ITEM, COMMAND_SEEK_TO_DEFAULT_POSITION, COMMAND_SEEK_TO_MEDIA_ITEM,
        COMMAND_SEEK_TO_NEXT_MEDIA_ITEM, COMMAND_SEEK_TO_PREVIOUS_MEDIA_ITEM, COMMAND_SEEK_TO_NEXT, COMMAND_SEEK_TO_PREVIOUS,
        COMMAND_SET_SHUFFLE_MODE, COMMAND_SET_REPEAT_MODE, COMMAND_GET_TIMELINE, COMMAND_GET_CURRENT_MEDIA_ITEM, COMMAND_GET_METADATA,
        COMMAND_SET_MEDIA_ITEM, COMMAND_CHANGE_MEDIA_ITEMS, COMMAND_GET_DEVICE_VOLUME,
        COMMAND_SET_DEVICE_VOLUME_WITH_FLAGS, COMMAND_ADJUST_DEVICE_VOLUME_WITH_FLAGS,
    ).build()

    private fun positionMs(u: ConnectUi): Long {
        val s = u.state ?: return 0
        var pos = (s.position * 1000).toLong()
        if (s.playing) pos += (clock() - u.at).coerceAtLeast(0)
        val dur = (s.duration * 1000).toLong()
        return if (dur > 0) pos.coerceAtMost(dur) else pos
    }

    override fun getState(): State {
        val u = link.ui.value
        val s = u.state ?: RemoteState()
        val ctx = s.context?.let { PlayContext(it.label, nativeRoute(it.href) ?: "") }
        val src = source()
        val items = u.queue.mapIndexed { i, t ->
            val item = if (src != null) t.toControllerItem(src, ctx) else t.toControllerItem(null as String?, ctx)
            MediaItemData.Builder("$i:${t.id}").setMediaItem(item).setDurationUs((t.duration * 1_000_000).toLong()).build()
        }
        val b = State.Builder().setAvailableCommands(commands).setPlaylist(items)
            .setShuffleModeEnabled(s.shuffle).setRepeatMode(REPEATS.indexOf(s.repeat).coerceAtLeast(0).let { listOf(REPEAT_MODE_OFF, REPEAT_MODE_ALL, REPEAT_MODE_ONE)[it] })
            .setDeviceInfo(REMOTE_DEVICE).setDeviceVolume((s.volume * 100).roundToInt().coerceIn(0, 100))
        if (items.isEmpty()) return b.setPlaybackState(STATE_IDLE).setPlayWhenReady(false, PLAY_WHEN_READY_CHANGE_REASON_REMOTE).build()
        val pos = positionMs(u)
        return b.setCurrentMediaItemIndex(s.index.coerceIn(0, items.lastIndex))
            .setContentPositionMs(if (s.playing) PositionSupplier.getExtrapolating(pos, 1f) else PositionSupplier.getConstant(pos))
            .setPlaybackState(STATE_READY).setPlayWhenReady(s.playing, PLAY_WHEN_READY_CHANGE_REASON_REMOTE)
            .build()
    }

    private val done: ListenableFuture<*> get() = Futures.immediateVoidFuture()

    override fun handleSetPlayWhenReady(playWhenReady: Boolean): ListenableFuture<*> {
        val pos = positionMs(link.ui.value) / 1000.0
        link.optimistic { it.copy(playing = playWhenReady, position = pos) }
        link.cmd(if (playWhenReady) "play" else "pause")
        return done
    }

    override fun handleSeek(mediaItemIndex: Int, positionMs: Long, seekCommand: Int): ListenableFuture<*> {
        val current = link.ui.value.state?.index ?: 0
        when (seekCommand) {
            COMMAND_SEEK_TO_NEXT, COMMAND_SEEK_TO_NEXT_MEDIA_ITEM -> link.cmd("next")
            COMMAND_SEEK_TO_PREVIOUS, COMMAND_SEEK_TO_PREVIOUS_MEDIA_ITEM -> link.cmd("prev")
            else -> {
                val ms = if (positionMs == C.TIME_UNSET) 0 else positionMs
                if (mediaItemIndex == current) {
                    link.optimistic { it.copy(position = ms / 1000.0) }
                    link.cmd("seek", JsonPrimitive(ms / 1000.0))
                } else {
                    link.optimistic { it.copy(index = mediaItemIndex, position = 0.0) }
                    link.cmd("jumpTo", JsonPrimitive(mediaItemIndex))
                }
            }
        }
        return done
    }

    override fun handleSetShuffleModeEnabled(shuffleModeEnabled: Boolean): ListenableFuture<*> {
        if (shuffleModeEnabled != (link.ui.value.state?.shuffle ?: false)) {
            link.optimistic { it.copy(shuffle = shuffleModeEnabled) }
            link.cmd("toggleShuffle")
        }
        return done
    }

    override fun handleSetRepeatMode(repeatMode: Int): ListenableFuture<*> {
        val want = when (repeatMode) { REPEAT_MODE_ALL -> "all"; REPEAT_MODE_ONE -> "one"; else -> "off" }
        val have = link.ui.value.state?.repeat ?: "off"
        val steps = (REPEATS.indexOf(want) - REPEATS.indexOf(have) + 3) % 3
        repeat(steps) { link.cmd("cycleRepeat") }
        if (steps > 0) link.optimistic { it.copy(repeat = want) }
        return done
    }

    override fun handleSetDeviceVolume(deviceVolume: Int, flags: Int): ListenableFuture<*> {
        val v = deviceVolume.coerceIn(0, 100) / 100.0
        link.optimistic { it.copy(volume = v) }
        link.cmd("setVolume", JsonPrimitive(v))
        return done
    }

    override fun handleIncreaseDeviceVolume(flags: Int) = handleSetDeviceVolume(state.deviceVolume + 5, flags)
    override fun handleDecreaseDeviceVolume(flags: Int) = handleSetDeviceVolume(state.deviceVolume - 5, flags)

    override fun handleSetMediaItems(mediaItems: MutableList<MediaItem>, startIndex: Int, startPositionMs: Long): ListenableFuture<*> {
        val tracks = mediaItems.mapNotNull { it.track() }
        if (tracks.isEmpty()) return done
        val ctx = mediaItems.firstOrNull()?.playContext()
        val opts = JsonObject(ctx?.let { mapOf("context" to contextJson(WebContext(it.label, webHref(it.route)))) } ?: emptyMap())
        link.cmd("playList", tracksJson(tracks), JsonPrimitive(startIndex.coerceAtLeast(0)), opts)
        return done
    }

    override fun handleAddMediaItems(index: Int, mediaItems: MutableList<MediaItem>): ListenableFuture<*> {
        val tracks = mediaItems.mapNotNull { it.track() }
        if (tracks.isEmpty()) return done
        val current = link.ui.value.state?.index ?: 0
        link.cmd(if (index == current + 1) "playNext" else "addToQueue", tracksJson(tracks))
        return done
    }

    override fun handleRemoveMediaItems(fromIndex: Int, toIndex: Int): ListenableFuture<*> {
        for (i in toIndex - 1 downTo fromIndex) link.cmd("removeAt", JsonPrimitive(i))
        return done
    }

    /** One song at a time (the queue sheet drags one): sent as "moveItem", shown moved straight away. */
    override fun handleMoveMediaItems(fromIndex: Int, toIndex: Int, newIndex: Int): ListenableFuture<*> {
        val u = link.ui.value
        if (toIndex - fromIndex != 1) return done
        val (from, to) = queueMove(u.queue.size, u.state?.index ?: 0, fromIndex, newIndex) ?: return done
        link.optimisticQueue { q -> moveItem(q, from, to) }
        link.cmd("moveItem", JsonPrimitive(from), JsonPrimitive(to))
        return done
    }

    override fun handlePrepare(): ListenableFuture<*> = done
    override fun handleStop(): ListenableFuture<*> = handleSetPlayWhenReady(false)
    override fun handleRelease(): ListenableFuture<*> = done
}
