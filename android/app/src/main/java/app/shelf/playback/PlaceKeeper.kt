package app.shelf.playback

import app.shelf.data.Track

/** Tracks this long (live sets, DJ mixes, audiobooks) pick up where you stopped, as on the web. */
const val LONG_SECONDS = 15 * 60

fun isLong(t: Track) = t.duration >= LONG_SECONDS

/**
 * Keeps your place in a long track on the server: every 15 seconds while it plays, when it's
 * paused, and when it's left for another song (at its end, the server forgets it).
 */
class PlaceKeeper(private val send: (trackId: Int, seconds: Double) -> Unit, private val everyMs: Long = 15_000) {
    private var id: Int? = null
    private var at = 0.0
    private var sentAt = 0L

    /** Where the playing song is (about every second). */
    fun onPosition(t: Track?, seconds: Double, nowMs: Long) {
        if (t == null || !isLong(t)) { id = null; return }
        if (t.id != id) { id = t.id; sentAt = nowMs }
        at = seconds
        if (nowMs - sentAt >= everyMs) { sentAt = nowMs; send(t.id, seconds) }
    }

    fun paused() { id?.let { send(it, at) } }

    /** Another song started: the long one's place is kept where it was last seen. */
    fun leftFor(next: Track?) {
        val was = id ?: return
        if (next?.id != was) { send(was, at); id = null }
    }
}
