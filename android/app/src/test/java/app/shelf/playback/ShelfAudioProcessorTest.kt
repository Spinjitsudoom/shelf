package app.shelf.playback

import androidx.media3.common.C
import androidx.media3.common.audio.AudioProcessor.AudioFormat
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.PI
import kotlin.math.sin

class ShelfAudioProcessorTest {
    private val rate = 44100

    /** Run interleaved 16-bit stereo samples through the processor and get what comes out. */
    private fun run(p: ShelfAudioProcessor, samples: ShortArray, channels: Int = 2): ShortArray {
        p.configure(AudioFormat(rate, channels, C.ENCODING_PCM_16BIT))
        p.flush()
        val input = ByteBuffer.allocateDirect(samples.size * 2).order(ByteOrder.nativeOrder())
        samples.forEach { input.putShort(it) }
        input.flip()
        if (!p.isActive) return samples
        p.queueInput(input)
        val out = p.output
        return ShortArray(out.remaining() / 2) { out.short }
    }

    private fun sine(freq: Double, amp: Double, n: Int) = ShortArray(n * 2) { i -> (amp * 32767 * sin(2 * PI * freq * (i / 2) / rate)).toInt().toShort() }

    @Test fun peakingHitsItsGain() {
        assertEquals(6.0, peaking(1000.0, 6.0, 1.0, rate.toDouble()).magnitudeDb(1000.0, rate.toDouble()), 0.1)
        assertEquals(0.0, peaking(1000.0, 6.0, 1.0, rate.toDouble()).magnitudeDb(15000.0, rate.toDouble()), 0.5)
    }

    @Test fun flatIsPassthrough() {
        val p = ShelfAudioProcessor().apply { setup(List(6) { 0.0 }, 0f, false) }
        val s = sine(440.0, 0.5, 2000)
        assertArrayEquals(s, run(p, s))
    }

    @Test fun boostIsClamped() {
        // +12 dB at 1 kHz on a loud 1 kHz tone: about four times full scale. A peaking band doesn't shift the
        // phase at its own frequency, so every loud sample must keep its sign (overflow would flip it) and sit at the rail.
        val p = ShelfAudioProcessor().apply { setup(listOf(0.0, 0.0, 0.0, 12.0, 0.0, 0.0), 0f, false) }
        val input = sine(1000.0, 0.99, 6000)
        val out = run(p, input)
        for (i in 4000 until out.size step 2) {
            if (kotlin.math.abs(input[i].toInt()) > 16000) {
                assertTrue("sample $i: ${input[i]} came out ${out[i]}", (input[i] > 0) == (out[i] > 0))
                assertTrue("sample $i at the rail", out[i] == Short.MAX_VALUE || out[i] == Short.MIN_VALUE)
            }
        }
    }

    @Test fun balanceLeftSilencesRight() {
        val p = ShelfAudioProcessor().apply { setup(null, -1f, false) }
        val out = run(p, sine(440.0, 0.5, 1000))
        assertTrue((1 until out.size step 2).all { out[it] == 0.toShort() })
        assertTrue((0 until out.size step 2).any { out[it] != 0.toShort() })
    }

    @Test fun monoAveragesChannels() {
        val p = ShelfAudioProcessor().apply { setup(null, 0f, true) }
        val out = run(p, shortArrayOf(1000, 3000, -2000, 0))
        assertArrayEquals(shortArrayOf(2000, 2000, -1000, -1000), out)
    }

    @Test fun presetsMatchWeb() {
        assertEquals(listOf(60, 150, 400, 1000, 2400, 15000), Eq.BANDS)
        assertEquals(listOf(4.5, 2.5, -3.0, -0.5, 3.5, 3.0), Eq.PRESETS["Metal"])
        assertEquals(List(6) { 0.0 }, Eq.PRESETS["Flat"])
        assertEquals(23, Eq.PRESETS.size)
    }

    /** How much [p] changes a sine at [freq], in dB (measured after it settles). */
    private fun gainAt(p: ShelfAudioProcessor, freq: Double): Double {
        val input = sine(freq, 0.25, 22050)
        val out = run(p, input)
        fun rms(a: ShortArray) = kotlin.math.sqrt((11025 until a.size step 2).sumOf { a[it].toDouble() * a[it] } / ((a.size - 11025) / 2))
        return 20 * kotlin.math.log10(rms(out) / rms(input))
    }

    @Test fun bassCutCutsBass() {
        val p = ShelfAudioProcessor().apply { setTransition(-26.0, null, null) }
        assertTrue(gainAt(p, 60.0) < -20)
        assertEquals(0.0, gainAt(ShelfAudioProcessor().apply { setTransition(-26.0, null, null) }, 5000.0), 0.5)
    }

    @Test fun highpassThinsOut() {
        assertTrue(gainAt(ShelfAudioProcessor().apply { setTransition(0.0, 1400.0, null) }, 100.0) < -40)
        assertEquals(0.0, gainAt(ShelfAudioProcessor().apply { setTransition(0.0, 1400.0, null) }, 5000.0), 0.5)
    }

    @Test fun noTransitionIsPassthrough() {
        val p = ShelfAudioProcessor().apply { setTransition(0.0, null, null) }
        val s = sine(440.0, 0.5, 2000)
        assertArrayEquals(s, run(p, s))
    }
}
