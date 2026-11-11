package app.shelf.playback

import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackParameters
import androidx.media3.common.Player
import androidx.media3.common.Timeline
import androidx.media3.exoplayer.ExoPlayer
import app.shelf.data.Track

/**
 * Two players ("decks"), so one song can hand over to the next with both playing: a crossfade,
 * or a Mix transition (beat-matched, with the bass swap and filter sweeps).
 *
 * The [current] deck holds the queue. When a transition is due, the other deck starts the next
 * song at its planned point and tempo, and [tick] moves both decks' volume and effects along the
 * plan. At the end the other deck takes over: the rest of the queue is added around the song it's
 * playing (which doesn't interrupt it), the old deck stops, and [onSwap] tells the service, so the
 * media session, Connect, the widget and the play counter follow. A skip, pause or seek during a
 * transition ends it at once with the new song at full level; seeking within the old song calls
 * the transition off instead.
 */
class Decks(
    private val a: ExoPlayer,
    private val b: ExoPlayer,
    private val effects: (Player) -> ShelfAudioProcessor,
    /** How (and whether) [cur] hands over to [nxt] on this deck: Mix, the crossfade setting, or null for none. */
    private val planFor: (cur: Track, nxt: Track, durationS: Double, deck: Player) -> Plan?,
    /** A deck's volume before any transition: levelling, the volume set over Connect, the sleep timer's fade. */
    private val baseVolume: (Player) -> Float,
) {
    var current: ExoPlayer = a
        private set
    private val other get() = if (current === a) b else a
    var onSwap: (ExoPlayer) -> Unit = {}

    private class Active(val plan: Plan, val startedAt: Long, val outIndex: Int, val incoming: MediaItem)
    private var active: Active? = null
    private var plannedKey: String? = null
    private var planned: Plan? = null
    private var easing: Pair<Float, Long>? = null // after a beat-matched transition: easing back to its own tempo
    private var now = 0L

    val inTransition get() = active != null

    init {
        // A skip, pause or seek on the old deck mid-transition ends it.
        val watch = object : Player.Listener {
            override fun onEvents(player: Player, events: Player.Events) {
                val t = active ?: return
                if (player !== current) return
                val skipped = events.contains(Player.EVENT_MEDIA_ITEM_TRANSITION) && player.currentMediaItemIndex != t.outIndex
                val paused = events.contains(Player.EVENT_PLAY_WHEN_READY_CHANGED) && !player.playWhenReady
                val seekedHere = events.contains(Player.EVENT_POSITION_DISCONTINUITY) && player.currentMediaItemIndex == t.outIndex &&
                    player.currentPosition < (t.plan.start * 1000).toLong() - 500
                when {
                    skipped || paused -> finish(pausedNow = paused)
                    seekedHere -> callOff()
                }
            }
            // The song coming in won't play: no transition; the playing song carries on (and the queue moves on at its end).
            override fun onPlayerError(error: androidx.media3.common.PlaybackException) { if (active != null) callOff() }
        }
        a.addListener(watch); b.addListener(watch)
    }

    /** Listen to whichever deck is current (events from the incoming deck wait until it takes over). */
    fun addListener(l: Player.Listener) {
        for (deck in listOf(a, b)) deck.addListener(object : Player.Listener {
            override fun onEvents(player: Player, events: Player.Events) { if (deck === current) l.onEvents(player, events) }
            override fun onMediaItemTransition(mediaItem: MediaItem?, reason: Int) { if (deck === current) l.onMediaItemTransition(mediaItem, reason) }
            override fun onIsPlayingChanged(isPlaying: Boolean) { if (deck === current) l.onIsPlayingChanged(isPlaying) }
            override fun onPlayWhenReadyChanged(playWhenReady: Boolean, reason: Int) { if (deck === current) l.onPlayWhenReadyChanged(playWhenReady, reason) }
            override fun onPlaybackStateChanged(playbackState: Int) { if (deck === current) l.onPlaybackStateChanged(playbackState) }
            override fun onPlayerError(error: androidx.media3.common.PlaybackException) { if (deck === current) l.onPlayerError(error) }
            override fun onTimelineChanged(timeline: Timeline, reason: Int) { if (deck === current) l.onTimelineChanged(timeline, reason) }
            override fun onPositionDiscontinuity(oldPosition: Player.PositionInfo, newPosition: Player.PositionInfo, reason: Int) {
                if (deck === current) l.onPositionDiscontinuity(oldPosition, newPosition, reason)
            }
        })
    }

    /** Volumes for now: the current deck at its own level, or both along the transition. */
    fun applyVolumes() {
        val t = active
        if (t == null) {
            current.volume = baseVolume(current)
            other.volume = 0f
            return
        }
        val s = ((now - t.startedAt) / 1000.0).coerceAtLeast(0.0)
        val out = levels(t.plan, "out", s)
        val inc = levels(t.plan, "in", s)
        current.volume = (baseVolume(current) * out.gain).toFloat()
        other.volume = (baseVolume(other) * inc.gain).toFloat()
        effects(current).setTransition(out.bassDb, out.highpassHz, out.lowpassHz)
        effects(other).setTransition(inc.bassDb, inc.highpassHz, inc.lowpassHz)
    }

    /** Called often (every 50 ms or so) with the time: starts, moves along, or finishes a transition. */
    fun tick(nowMs: Long) {
        now = nowMs
        easing?.let { (from, at) ->
            val u = ((nowMs - at) / 4000.0).coerceIn(0.0, 1.0).toFloat()
            current.playbackParameters = PlaybackParameters(from + (1f - from) * u)
            if (u >= 1f) easing = null
        }
        val t = active
        if (t != null) {
            if (nowMs - t.startedAt >= (t.plan.length * 1000).toLong()) finish(pausedNow = false) else applyVolumes()
            return
        }
        val p = current
        if (!p.playWhenReady || p.playbackState == Player.STATE_ENDED) return
        // Repeat one: the song plays again (Media3's "next" would skip to the next song here).
        if (p.repeatMode == Player.REPEAT_MODE_ONE) return
        val next = p.nextMediaItemIndex
        if (next == C.INDEX_UNSET) return
        val cur = p.currentMediaItem?.track() ?: return
        val nxt = p.getMediaItemAt(next).track() ?: return
        val dur = p.duration.takeIf { it != C.TIME_UNSET && it > 0 }?.div(1000.0) ?: cur.duration
        val key = "${p.currentMediaItemIndex}:${cur.id}>${nxt.id}:${cur.transition}:$dur"
        if (key != plannedKey) { plannedKey = key; planned = planFor(cur, nxt, dur, p) }
        val plan = planned ?: return
        if (p.currentPosition < (plan.start * 1000).toLong()) return
        if (plan.length <= 0) {
            // A cut: straight into the next song at its start point.
            if (plan.start < dur - 0.3) p.seekTo(next, (plan.inStart * 1000).toLong())
            plannedKey = null
            return
        }
        begin(plan, next)
    }

    private fun begin(plan: Plan, next: Int) {
        val incoming = current.getMediaItemAt(next)
        val deck = other
        deck.setMediaItems(listOf(incoming), 0, (plan.inStart * 1000).toLong())
        deck.playbackParameters = PlaybackParameters(plan.rate.toFloat()) // tempo matched, pitch kept
        deck.volume = 0f
        deck.prepare()
        deck.play()
        active = Active(plan, now, current.currentMediaItemIndex, incoming)
        applyVolumes()
    }

    /** End the transition now: the incoming deck takes over with the whole queue, at full level. */
    private fun finish(pausedNow: Boolean) {
        val t = active ?: return
        active = null
        plannedKey = null
        val old = current
        val inc = other
        // Where the incoming song is in the old deck's queue now (songs may have been added or removed meanwhile).
        val items = (0 until old.mediaItemCount).map { old.getMediaItemAt(it) }
        val at = (t.outIndex + 1 until items.size).firstOrNull { items[it].mediaId == t.incoming.mediaId }
            ?: items.indexOfFirst { it.mediaId == t.incoming.mediaId }.takeIf { it >= 0 }
        if (at != null) {
            val before = items.subList(0, (t.outIndex + 1).coerceAtMost(at))
            // Songs put in between during the transition ("play next") play after the one coming in.
            val after = items.subList((t.outIndex + 1).coerceAtMost(at), at) + items.subList(at + 1, items.size)
            if (before.isNotEmpty()) inc.addMediaItems(0, before)
            if (after.isNotEmpty()) inc.addMediaItems(after)
        }
        inc.repeatMode = old.repeatMode
        inc.shuffleModeEnabled = old.shuffleModeEnabled
        // Only the deck that plays for the person holds audio focus (two would pause each other).
        old.setAudioAttributes(old.audioAttributes, false)
        old.stop()
        old.clearMediaItems()
        old.playbackParameters = PlaybackParameters.DEFAULT
        inc.setAudioAttributes(inc.audioAttributes, true)
        if (pausedNow) inc.pause()
        effects(old).setTransition(0.0, null, null)
        effects(inc).setTransition(0.0, null, null)
        current = inc
        if (t.plan.rate != 1.0) easing = t.plan.rate.toFloat() to now
        applyVolumes()
        onSwap(inc)
    }

    /** Seeking within the old song: no transition after all; the incoming deck stops. */
    private fun callOff() {
        active = null
        plannedKey = null
        other.stop(); other.clearMediaItems(); other.playbackParameters = PlaybackParameters.DEFAULT
        effects(current).setTransition(0.0, null, null); effects(other).setTransition(0.0, null, null)
        applyVolumes()
    }
}
