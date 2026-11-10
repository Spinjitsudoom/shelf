package app.shelf.playback

import app.shelf.data.Track
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.floor
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.roundToInt
import kotlin.math.sin

/*
 * Mix: how one song hands over to the next, like a DJ would. A port of the web app's
 * transitions.js, so a playlist mixes the same on the phone as in the browser.
 *
 * Each song carries "mix points" measured on the server (analysis.py): where its sound starts
 * and ends, its intro and outro, its first beat, and a beat near the outro with the beat length.
 */

/** A song's mix points, in seconds. */
@Serializable
data class MixPoints(
    val start: Double? = null, val end: Double? = null, val intro: Double? = null, val outro: Double? = null,
    val firstBeat: Double? = null, val outBeat: Double? = null, val outPeriod: Double? = null, val inPeriod: Double? = null,
)

val STYLES = listOf("auto", "blend", "swap", "rise", "sweep", "fade", "cut")
private const val MAX_STRETCH = 0.08 // the most a song's tempo is changed to match
private const val BASS_CUT = -26.0 // dB
private val HP = 30.0 to 1400.0 // Hz: the outgoing song's high-pass sweeps up through this
private val LP = 350.0 to 20000.0 // Hz: the incoming song's low-pass opens through this

private data class Parts(val volume: String, val eq: String, val filter: String, val bars: Double? = null, val seconds: Double? = null,
                         val free: Boolean = false, val cut: Boolean = false)

private val PRESETS = mapOf(
    "blend" to Parts("dj", "swap", "none", bars = 8.0),
    "swap" to Parts("quick", "swap", "none", bars = 4.0),
    "rise" to Parts("dj", "none", "rise", bars = 4.0),
    "sweep" to Parts("smooth", "none", "sweep", bars = 4.0),
    "fade" to Parts("smooth", "none", "none", seconds = 8.0, free = true), // free: no tempo matching
    "cut" to Parts("cut", "none", "none", cut = true),
)

/** When and how a song hands over: [start] in its time, [inStart] in the next song's, [length] in real seconds. */
data class Plan(
    val style: String, val start: Double, val length: Double, val inStart: Double = 0.0, val rate: Double = 1.0,
    val beatmatch: Boolean = false, val beats: Int = 0, val volume: String = "smooth", val eq: String = "none", val filter: String = "none",
)

data class Match(val rate: Double, val mult: Double, val period: Double)

/** Tempo match between an outgoing and incoming song's mix points, or null if too far apart. */
fun tempoMatch(out: MixPoints?, inc: MixPoints?): Match? {
    val op = out?.outPeriod ?: return null
    val ip = inc?.inPeriod ?: return null
    var best: Match? = null
    // A song detected at half or double tempo can still be matched beat for beat.
    for (mult in listOf(1.0, 2.0, 0.5)) {
        val period = ip / mult
        val rate = period / op
        if (best == null || abs(rate - 1) < abs(best.rate - 1)) best = Match(rate, mult, period)
    }
    return best?.takeIf { abs(it.rate - 1) <= MAX_STRETCH + 1e-12 }
}

private fun camelotOk(a: String?, b: String?): Boolean {
    if (a.isNullOrBlank() || b.isNullOrBlank()) return true // unknown keys: don't hold it against them
    val n = { c: String -> c.takeWhile(Char::isDigit).toIntOrNull() ?: 0 }
    if (a == b || n(a) == n(b)) return true // same, or relative major/minor
    if (a.last() != b.last()) return false
    val d = abs(n(a) - n(b))
    return d == 1 || d == 11
}

/** The preset "auto" turns into for this pair. */
fun autoStyle(cur: Track, nxt: Track): String {
    if (cur.mix == null || nxt.mix == null || tempoMatch(cur.mix, nxt.mix) == null) return "fade"
    return if (camelotOk(cur.camelot, nxt.camelot)) "blend" else "swap"
}

private class Resolved(val style: String, val parts: Parts, val shift: Double)

/** A stored transition ("swap", or the editor's object) with the preset filled in under what was changed. */
private fun resolve(cur: Track, nxt: Track, setting: JsonElement?): Resolved {
    val obj = setting as? JsonObject
    val name = ((obj?.get("preset") ?: setting) as? JsonPrimitive)?.contentOrNull?.takeIf { it in STYLES } ?: "auto"
    val style = if (name == "auto") autoStyle(cur, nxt) else name
    val base = PRESETS.getValue(style)
    fun str(k: String) = (obj?.get(k) as? JsonPrimitive)?.contentOrNull
    fun num(k: String) = (obj?.get(k) as? JsonPrimitive)?.doubleOrNull
    val parts = base.copy(volume = str("volume") ?: base.volume, eq = str("eq") ?: base.eq, filter = str("filter") ?: base.filter,
        bars = num("bars") ?: base.bars, seconds = num("seconds") ?: base.seconds)
    return Resolved(style, parts, num("shift") ?: 0.0)
}

/** When and how [cur] hands over to [nxt]. [duration] is cur's real length in seconds. */
fun plan(cur: Track, nxt: Track, setting: JsonElement?, duration: Double = cur.duration): Plan {
    val r = resolve(cur, nxt, setting)
    val p = r.parts
    val m = cur.mix; val n = nxt.mix
    val end = min(m?.end ?: duration, if (duration > 0) duration else Double.POSITIVE_INFINITY)
    fun base(start: Double, length: Double, inStart: Double) = Plan(r.style, start, length, inStart, volume = p.volume, eq = p.eq, filter = p.filter)

    if (p.cut) return base(end + r.shift, 0.0, n?.start ?: 0.0)

    val match = if (!p.free && m != null && n != null) tempoMatch(m, n) else null
    if (match != null && m!!.outBeat != null && n!!.firstBeat != null) {
        val per = m.outPeriod!!
        val outBeat = m.outBeat!!
        // End the transition just after the outro starts winding down, and start it on a bar.
        val e = min(end, (m.outro ?: end) + 4 * per)
        val earliest = max(m.intro ?: 0.0, duration * 0.3)
        var beats = ((p.bars ?: 8.0) * 4).roundToInt().toDouble()
        while (beats > 4 && beats * per > e - earliest) beats /= 2
        if (beats * per <= end - earliest) {
            val k = floor((e - beats * per - outBeat) / per / 4) * 4 + (r.shift * 4).roundToInt()
            var start = outBeat + k * per
            while (start + beats * per > end + 0.01) start -= 4 * per // the song has to still be playing
            while (start < earliest - per) start += 4 * per
            if (start > 0) return base(start, beats * per, n.firstBeat!!).copy(rate = match.rate, beatmatch = true, beats = beats.roundToInt())
        }
    }

    // Not beat-matched: a crossfade timed to the outro (here the shift is in seconds).
    val e = if (m != null) min(end, (m.outro ?: end) + 3) else end
    val length = min(p.seconds ?: 8.0, max(2.0, (if (duration > 0) duration else 30.0) / 4))
    val start = max(0.0, min(end - length, e - length + r.shift))
    return base(start, length, n?.start ?: 0.0)
}

/** The plain crossfade setting (Mix off): [seconds] at the end of each song, but albums played in order stay seamless. */
fun crossfadePlan(seconds: Int, albums: Boolean, shuffle: Boolean, cur: Track, nxt: Track, duration: Double): Plan? {
    if (seconds <= 0) return null
    if (!shuffle && cur.albumId == nxt.albumId && !albums) return null
    val length = min(seconds.toDouble(), duration / 3)
    return Plan("fade", duration - length, length, 0.0, volume = "smooth")
}

/** One deck's sound at a moment of a transition: its volume (0..1), its bass (dB) and its filters (Hz, null: none). */
data class Levels(val gain: Double, val bassDb: Double, val highpassHz: Double?, val lowpassHz: Double?)

/** [side] "in" or "out", [t] seconds into the transition: equal-power volume curves, the bass swap or cut, and the sweeps. */
fun levels(plan: Plan, side: String, t: Double): Levels {
    val big = plan.length
    val (inCurve, outCurve) = when (plan.volume) {
        "dj" -> doubleArrayOf(0.0, big * 0.5, 0.0, 1.0) to doubleArrayOf(big * 0.5, big, 1.0, 0.0)
        "quick" -> doubleArrayOf(0.0, big * 0.25, 0.0, 1.0) to doubleArrayOf(big * 0.625, big, 1.0, 0.0)
        "cut" -> doubleArrayOf(big * 0.5 - 0.02, big * 0.5 + 0.02, 0.0, 1.0) to doubleArrayOf(big * 0.5 - 0.02, big * 0.5 + 0.02, 1.0, 0.0)
        else -> doubleArrayOf(0.0, big, 0.0, 1.0) to doubleArrayOf(0.0, big, 1.0, 0.0)
    }
    val (t0, t1, a, b) = (if (side == "in") inCurve else outCurve).let { listOf(it[0], it[1], it[2], it[3]) }
    val gain = when {
        t <= t0 -> a
        t >= t1 -> b
        else -> {
            val u = (t - t0) / (t1 - t0)
            if (a < b) a + (b - a) * sin(u * PI / 2) else b + (a - b) * cos(u * PI / 2)
        }
    }
    val bass = when {
        plan.eq == "swap" && side == "in" -> if (t < big * 0.5) BASS_CUT else 0.0
        plan.eq == "swap" && side == "out" -> if (t >= big * 0.5) BASS_CUT else 0.0
        plan.eq == "kill" && side == "out" -> BASS_CUT
        else -> 0.0
    }
    val u = if (big > 0) (t / big).coerceIn(0.0, 1.0) else 1.0
    val hp = if (side == "out" && (plan.filter == "rise" || plan.filter == "sweep")) HP.first * (HP.second / HP.first).pow(u) else null
    val lp = if (side == "in" && (plan.filter == "wash" || plan.filter == "sweep")) LP.first * (LP.second / LP.first).pow(u) else null
    return Levels(gain, bass, hp, lp)
}
