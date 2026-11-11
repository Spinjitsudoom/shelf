package app.shelf.playback

/** What's playing somewhere: the song, where in it, and whether it's playing. */
data class Here(val trackId: Int?, val positionS: Double, val playing: Boolean)

/** What to do to follow the host: load their song, seek, and/or play or pause (null: leave it). */
data class Step(val load: Boolean = false, val seekTo: Double? = null, val play: Boolean? = null)

/** How far apart (seconds) before seeking: closer than this, a seek would only stutter. */
const val PARTY_TOLERANCE = 2.0

/**
 * Party mode, listening along: what this device should do to play what the host plays, where
 * they are in it. Another song (or none here) loads the host's at their place; drifting apart
 * seeks; pausing and playing follow; the host stopping pauses here.
 */
fun follow(here: Here, host: Here): Step {
    if (host.trackId == null) return if (here.playing) Step(play = false) else Step()
    if (here.trackId != host.trackId) return Step(load = true, seekTo = host.positionS, play = host.playing)
    val seek = if (kotlin.math.abs(here.positionS - host.positionS) > PARTY_TOLERANCE) host.positionS else null
    val play = if (here.playing != host.playing) host.playing else null
    return Step(seekTo = seek, play = play)
}

/** At someone's party as a guest: whose, and whether this device plays along. */
data class PartyJoin(val host: Int, val playHere: Boolean = true)
