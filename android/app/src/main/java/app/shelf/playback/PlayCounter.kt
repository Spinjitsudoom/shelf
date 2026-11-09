package app.shelf.playback

/**
 * When a song counts as played (for history, mixes and scrobbling), the same rule as the web
 * app: heard for half its length or four minutes, whichever comes first. Only time actually
 * listened counts (steps forward under 2 s), so seeking ahead doesn't, and it counts once
 * each time the song starts.
 */
class PlayCounter(private val onPlayed: (Int) -> Unit) {
    private var id = -1
    private var duration = 0.0
    private var heard = 0.0
    private var last: Double? = null
    private var fired = false

    fun onTrackStarted(id: Int, durationS: Double) {
        this.id = id
        duration = durationS
        heard = 0.0
        last = null
        fired = false
    }

    fun onPosition(positionS: Double) {
        last?.let { val step = positionS - it; if (step > 0 && step < 2) heard += step }
        last = positionS
        if (!fired && id >= 0 && duration > 0 && heard >= minOf(240.0, duration / 2)) {
            fired = true
            onPlayed(id)
        }
    }
}
