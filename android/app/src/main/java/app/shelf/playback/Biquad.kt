package app.shelf.playback

import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.log10
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.sqrt

/** The equalizer's bands and presets: the web app's (settings.js), dB per band from 60 Hz to 15 kHz. */
object Eq {
    val BANDS = listOf(60, 150, 400, 1000, 2400, 15000)
    val LABELS = listOf("60", "150", "400", "1k", "2.4k", "15k")
    val PRESETS: Map<String, List<Double>> = linkedMapOf(
        "Flat" to listOf(0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        "Acoustic" to listOf(4.0, 3.0, 1.0, 1.5, 3.0, 2.5),
        "Bass Booster" to listOf(6.0, 4.0, 1.5, 0.0, 0.0, 0.0),
        "Bass Reducer" to listOf(-6.0, -4.0, -1.5, 0.0, 0.0, 0.0),
        "Classical" to listOf(4.0, 3.0, -1.0, -1.0, 2.0, 4.0),
        "Dance" to listOf(4.0, 6.0, 2.0, 0.0, 2.0, 1.0),
        "Deep" to listOf(4.5, 2.0, 1.0, -1.0, -3.0, -4.5),
        "Electronic" to listOf(4.0, 3.0, 0.0, -2.0, 2.0, 4.5),
        "Hip-Hop" to listOf(5.0, 4.0, 1.0, -1.0, 1.0, 2.5),
        "Jazz" to listOf(3.5, 2.0, -1.0, 1.5, 2.5, 3.5),
        "Latin" to listOf(2.5, 1.0, -1.0, -1.0, 2.0, 4.5),
        "Loudness" to listOf(5.5, 2.5, -1.0, -1.0, 2.0, 5.5),
        "Lounge" to listOf(-2.5, 0.0, 2.0, 1.0, 0.0, -1.0),
        // Shelf's own: tight low end, low-mid mud cut, guitar bite and cymbal air.
        "Metal" to listOf(4.5, 2.5, -3.0, -0.5, 3.5, 3.0),
        "Piano" to listOf(2.0, 1.0, 0.0, 2.5, 3.0, 2.0),
        "Pop" to listOf(-1.5, 1.0, 4.0, 4.0, 1.0, -1.5),
        "R&B" to listOf(5.0, 4.5, 1.0, -1.5, 2.0, 3.0),
        "Rock" to listOf(4.5, 3.0, -1.5, -1.0, 2.0, 4.0),
        "Small Speakers" to listOf(5.0, 4.0, 2.0, 0.0, -1.0, -3.0),
        "Spoken Word" to listOf(-3.0, -1.0, 2.0, 4.0, 3.0, 0.0),
        "Treble Booster" to listOf(0.0, 0.0, 0.0, 1.5, 4.0, 6.0),
        "Treble Reducer" to listOf(0.0, 0.0, 0.0, -1.5, -4.0, -6.0),
        "Vocal Booster" to listOf(-2.0, -1.0, 2.0, 4.0, 3.0, 0.0),
    )
}

/** One second-order filter, normalised (a0 = 1). */
data class Biquad(val b0: Double, val b1: Double, val b2: Double, val a1: Double, val a2: Double) {
    /** How much it boosts or cuts [freq], in dB. */
    fun magnitudeDb(freq: Double, rate: Double): Double {
        val w = 2 * PI * freq / rate
        val (c1, s1, c2, s2) = listOf(cos(w), -sin(w), cos(2 * w), -sin(2 * w))
        val nr = b0 + b1 * c1 + b2 * c2; val ni = b1 * s1 + b2 * s2
        val dr = 1 + a1 * c1 + a2 * c2; val di = a1 * s1 + a2 * s2
        return 20 * log10(sqrt(nr * nr + ni * ni) / sqrt(dr * dr + di * di))
    }
}

/** A peaking band (the Web Audio BiquadFilter "peaking" type, Audio EQ Cookbook formulas). */
fun peaking(freq: Double, gainDb: Double, q: Double, rate: Double): Biquad {
    val a = 10.0.pow(gainDb / 40)
    val w0 = 2 * PI * freq / rate
    val alpha = sin(w0) / (2 * q)
    val a0 = 1 + alpha / a
    return Biquad((1 + alpha * a) / a0, -2 * cos(w0) / a0, (1 - alpha * a) / a0, -2 * cos(w0) / a0, (1 - alpha / a) / a0)
}

/** A low shelf (Web Audio "lowshelf": slope 1), for Mix's bass swap and cut. */
fun lowShelf(freq: Double, gainDb: Double, rate: Double): Biquad {
    val a = 10.0.pow(gainDb / 40)
    val w0 = 2 * PI * freq / rate
    val c = cos(w0)
    val alpha = sin(w0) / 2 * sqrt(2.0)
    val s = 2 * sqrt(a) * alpha
    val a0 = (a + 1) + (a - 1) * c + s
    return Biquad(a * ((a + 1) - (a - 1) * c + s) / a0, 2 * a * ((a - 1) - (a + 1) * c) / a0, a * ((a + 1) - (a - 1) * c - s) / a0,
        -2 * ((a - 1) + (a + 1) * c) / a0, ((a + 1) + (a - 1) * c - s) / a0)
}

/** A 12 dB-per-octave high-pass, for Mix's "rise" (the outgoing song thins out). */
fun highPass(freq: Double, q: Double, rate: Double): Biquad {
    val w0 = 2 * PI * freq / rate
    val c = cos(w0); val alpha = sin(w0) / (2 * q); val a0 = 1 + alpha
    return Biquad((1 + c) / 2 / a0, -(1 + c) / a0, (1 + c) / 2 / a0, -2 * c / a0, (1 - alpha) / a0)
}

/** A 12 dB-per-octave low-pass, for Mix's "wash" (the incoming song opens up). */
fun lowPass(freq: Double, q: Double, rate: Double): Biquad {
    val w0 = 2 * PI * freq / rate
    val c = cos(w0); val alpha = sin(w0) / (2 * q); val a0 = 1 + alpha
    return Biquad((1 - c) / 2 / a0, (1 - c) / a0, (1 - c) / 2 / a0, -2 * c / a0, (1 - alpha) / a0)
}
