package app.shelf.playback

import androidx.annotation.OptIn
import androidx.media3.common.C
import androidx.media3.common.audio.AudioProcessor
import androidx.media3.common.audio.BaseAudioProcessor
import androidx.media3.common.util.UnstableApi
import java.nio.ByteBuffer
import kotlin.math.roundToInt

/**
 * Shelf's sound settings, applied to the music on its way to the speaker, in the web app's order:
 * mono, then balance, then the six-band equalizer (peaking bands, Q 1), then a limit at full
 * scale so a big boost clips instead of wrapping round.
 */
@OptIn(UnstableApi::class)
class ShelfAudioProcessor : BaseAudioProcessor() {
    private class Params(val eq: List<Double>?, val balance: Float, val mono: Boolean)

    @Volatile private var params = Params(null, 0f, false)
    private var built: Params? = null
    private var filters: List<Biquad> = emptyList()
    private var state = DoubleArray(0) // per channel, per band: x1, x2, y1, y2

    /** The settings: [eq] is dB per band (null: off), [balance] −1 (left) to 1 (right), [mono] both ears the same. */
    fun setup(eq: List<Double>?, balance: Float, mono: Boolean) {
        params = Params(eq?.takeIf { g -> g.any { it != 0.0 } }, balance.coerceIn(-1f, 1f), mono)
    }

    override fun onConfigure(inputAudioFormat: AudioProcessor.AudioFormat): AudioProcessor.AudioFormat {
        if (inputAudioFormat.encoding != C.ENCODING_PCM_16BIT && inputAudioFormat.encoding != C.ENCODING_PCM_FLOAT)
            throw AudioProcessor.UnhandledAudioFormatException(inputAudioFormat)
        return inputAudioFormat
    }

    override fun onFlush() { built = null }

    private fun rebuild(p: Params) {
        val rate = inputAudioFormat.sampleRate.toDouble()
        filters = p.eq?.mapIndexed { i, g -> peaking(Eq.BANDS[i].toDouble(), g, 1.0, rate) }.orEmpty()
        state = DoubleArray(inputAudioFormat.channelCount * filters.size * 4)
        built = p
    }

    override fun queueInput(inputBuffer: ByteBuffer) {
        val p = params
        if (built !== p) rebuild(p)
        val float = inputAudioFormat.encoding == C.ENCODING_PCM_FLOAT
        val channels = inputAudioFormat.channelCount
        val bytes = if (float) 4 else 2
        val frames = inputBuffer.remaining() / (bytes * channels)
        val out = replaceOutputBuffer(frames * bytes * channels)
        val frame = DoubleArray(channels)
        val left = if (p.balance > 0) 1.0 - p.balance else 1.0
        val right = if (p.balance < 0) 1.0 + p.balance else 1.0
        repeat(frames) {
            for (c in 0 until channels) frame[c] = if (float) inputBuffer.float.toDouble() else inputBuffer.short / 32768.0
            if (channels == 2) {
                if (p.mono) { val m = (frame[0] + frame[1]) / 2; frame[0] = m; frame[1] = m }
                frame[0] *= left; frame[1] *= right
            }
            for (c in 0 until channels) {
                var x = frame[c]
                for (b in filters.indices) {
                    val f = filters[b]; val s = (c * filters.size + b) * 4
                    val y = f.b0 * x + f.b1 * state[s] + f.b2 * state[s + 1] - f.a1 * state[s + 2] - f.a2 * state[s + 3]
                    state[s + 1] = state[s]; state[s] = x; state[s + 3] = state[s + 2]; state[s + 2] = y
                    x = y
                }
                if (float) out.putFloat(x.coerceIn(-1.0, 1.0).toFloat())
                else out.putShort((x * 32768).roundToInt().coerceIn(-32768, 32767).toShort())
            }
        }
        out.flip()
    }
}
