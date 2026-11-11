package app.shelf.playback

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.PI
import kotlin.math.ln
import kotlin.math.sin

class SpectrumTest {
    private val rate = 44100
    private fun bandOf(hz: Double) = (64 * ln(hz / 40.0) / ln(12000.0 / 40.0)).toInt()

    @Test fun aToneLightsItsBand() {
        val tone = FloatArray(2048) { (0.5 * sin(2 * PI * 1000.0 * it / rate)).toFloat() }
        val b = spectrumBands(tone, rate)
        assertEquals(64, b.size)
        assertTrue("1 kHz is loud: ${b[bandOf(1000.0)]}", b[bandOf(1000.0)] > 0.8f)
        assertTrue("100 Hz is quiet: ${b[bandOf(100.0)]}", b[bandOf(100.0)] < 0.2f)
    }

    @Test fun silenceIsFlat() = assertTrue(spectrumBands(FloatArray(2048), rate).all { it == 0f })

    @Test fun theTapGivesRecentSamplesFromAMomentAgo() {
        val tap = SpectrumTap()
        assertNull(tap.snapshot(2048, delayS = 0.0)) // nothing heard yet
        tap.configure(1000)
        repeat(4000) { tap.write(it.toFloat()) }
        val s = tap.snapshot(4, delayS = 0.5)!! // half a second back: the 4 samples before the last 500
        assertEquals(listOf(3496f, 3497f, 3498f, 3499f), s.toList())
    }
}
