package app.shelf.playback

import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.hypot
import kotlin.math.log10
import kotlin.math.sin

/**
 * For the visualizer: the last second or so of what's playing, as mono samples, written by the
 * audio processor (only while [listening], so it costs nothing otherwise) and read by Now Playing.
 * Audio is processed a little ahead of when it's heard, so readers look a moment back.
 */
class SpectrumTap {
    private val ring = FloatArray(1 shl 16)
    private val mask = ring.size - 1
    @Volatile private var count = 0L
    @Volatile var sampleRate = 44100
        private set

    fun configure(rate: Int) { sampleRate = rate; count = 0 }

    fun write(v: Float) { ring[(count and mask.toLong()).toInt()] = v; count++ }

    /** `n` samples ending `delayS` seconds before the newest, or null if there aren't enough yet. */
    fun snapshot(n: Int, delayS: Double = 0.25): FloatArray? {
        val end = count - (delayS * sampleRate).toLong()
        if (end < n || n > ring.size / 2) return null
        return FloatArray(n) { ring[((end - n + it) and mask.toLong()).toInt()] }
    }

    companion object {
        /** The one the player's processors write to and Now Playing reads. */
        val shared = SpectrumTap()
        @Volatile var listening = false
    }
}

/** Log-spaced bands, each 0..1 (`floor` dB silent, `ceil` dB full), as the web's visualizer. */
fun spectrumBands(samples: FloatArray, sampleRate: Int, count: Int = 64, lo: Double = 40.0, hi: Double = 12000.0,
                  floor: Double = -90.0, ceil: Double = -25.0): FloatArray {
    val n = Integer.highestOneBit(samples.size)
    val re = DoubleArray(n); val im = DoubleArray(n)
    var wsum = 0.0
    for (i in 0 until n) { val w = 0.5 - 0.5 * cos(2 * PI * i / (n - 1)); re[i] = samples[i] * w; wsum += w }
    fft(re, im)
    val binHz = sampleRate.toDouble() / n
    return FloatArray(count) { b ->
        val f0 = lo * Math.pow(hi / lo, b.toDouble() / count); val f1 = lo * Math.pow(hi / lo, (b + 1.0) / count)
        val i0 = (f0 / binHz).toInt().coerceIn(1, n / 2 - 1); val i1 = Math.ceil(f1 / binHz).toInt().coerceIn(i0, n / 2 - 1)
        var peak = 0.0
        for (i in i0..i1) peak = maxOf(peak, hypot(re[i], im[i]) * 2 / wsum)
        val db = if (peak > 0) 20 * log10(peak) else Double.NEGATIVE_INFINITY
        ((db - floor) / (ceil - floor)).coerceIn(0.0, 1.0).toFloat()
    }
}

/** Bars rise at once and fall back gently. */
fun smoothBands(prev: FloatArray, next: FloatArray, fall: Float = 0.08f): FloatArray =
    FloatArray(next.size) { i -> if (next[i] > prev.getOrElse(i) { 0f }) next[i] else maxOf(next[i], prev.getOrElse(i) { 0f } - fall) }

/** In-place radix-2 FFT (n a power of two). */
private fun fft(re: DoubleArray, im: DoubleArray) {
    val n = re.size
    var j = 0
    for (i in 1 until n) {
        var bit = n shr 1
        while (j and bit != 0) { j = j xor bit; bit = bit shr 1 }
        j = j or bit
        if (i < j) { re[i] = re[j].also { re[j] = re[i] }; im[i] = im[j].also { im[j] = im[i] } }
    }
    var len = 2
    while (len <= n) {
        val ang = -2 * PI / len
        for (i in 0 until n step len) for (k in 0 until len / 2) {
            val wr = cos(ang * k); val wi = sin(ang * k)
            val ur = re[i + k]; val ui = im[i + k]
            val vr = re[i + k + len / 2] * wr - im[i + k + len / 2] * wi
            val vi = re[i + k + len / 2] * wi + im[i + k + len / 2] * wr
            re[i + k] = ur + vr; im[i + k] = ui + vi
            re[i + k + len / 2] = ur - vr; im[i + k + len / 2] = ui - vi
        }
        len = len shl 1
    }
}
