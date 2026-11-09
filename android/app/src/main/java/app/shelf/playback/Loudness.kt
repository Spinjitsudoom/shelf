package app.shelf.playback

import kotlin.math.pow

/** dB LUFS each level aims for (the web app's LOUDNESS_TARGETS). */
val LOUDNESS_TARGETS = mapOf("loud" to -11.0, "normal" to -14.0, "quiet" to -19.0)

/** How much to turn a song up or down so songs sound equally loud: the web app's rule. Normal
 * and Quiet never push a song into clipping (they stop 1 dB under its peak); Loud doesn't hold back. */
fun gainDb(lufs: Double?, peak: Double?, level: String): Double {
    if (lufs == null) return 0.0
    var db = (LOUDNESS_TARGETS[level] ?: -14.0) - lufs
    if (level != "loud" && peak != null) db = minOf(db, -1 - peak)
    return db.coerceIn(-24.0, 12.0)
}

/** The player's volume for a gain. The player can only turn down (volume ≤ 1), so loud songs
 * come down to meet quiet ones; quiet ones aren't raised. */
fun volumeFor(gainDb: Double): Float = minOf(1.0, 10.0.pow(gainDb / 20)).toFloat()
