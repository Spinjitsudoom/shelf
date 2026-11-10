package app.shelf.playback

import app.shelf.data.Track
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class TransitionTest {
    private val outMix = MixPoints(start = 0.0, end = 238.0, intro = 16.0, outro = 210.0, firstBeat = 0.5, outBeat = 200.0, outPeriod = 0.5, inPeriod = 0.5)
    private val inMix = MixPoints(start = 0.2, end = 230.0, intro = 12.0, outro = 200.0, firstBeat = 1.0, outBeat = 190.0, outPeriod = 0.5, inPeriod = 0.5)
    private fun t(id: Int, mix: MixPoints? = null, camelot: String? = null, album: Int = id, duration: Double = 240.0) =
        Track(id, "Song $id", "Band", albumId = album, duration = duration, mix = mix, camelot = camelot)

    @Test fun tempoMatchWithinEightPercent() {
        val out = MixPoints(outPeriod = 0.5)
        assertEquals(1.04, tempoMatch(out, MixPoints(inPeriod = 0.52))!!.rate, 1e-9)
        val half = tempoMatch(out, MixPoints(inPeriod = 1.0))!! // detected at half time: still beat for beat
        assertEquals(1.0, half.rate, 1e-9); assertEquals(2.0, half.mult, 0.0)
        assertNull(tempoMatch(out, MixPoints(inPeriod = 0.6)))
        assertNull(tempoMatch(MixPoints(), MixPoints(inPeriod = 0.5)))
    }

    @Test fun autoPicksBlendSwapOrFade() {
        assertEquals("blend", autoStyle(t(1, outMix, "8A"), t(2, inMix, "9A")))
        assertEquals("blend", autoStyle(t(1, outMix, "8A"), t(2, inMix, "8B")))
        assertEquals("swap", autoStyle(t(1, outMix, "8A"), t(2, inMix, "3B")))
        assertEquals("fade", autoStyle(t(1), t(2, inMix)))
    }

    @Test fun beatmatchedPlanStartsOnABarAndEndsBeforeTheEnd() {
        val p = plan(t(1, outMix), t(2, inMix), null, 240.0)
        assertEquals("blend", p.style)
        assertTrue(p.beatmatch)
        assertEquals(32, p.beats)
        assertEquals(16.0, p.length, 1e-9)
        assertEquals(196.0, p.start, 1e-9)
        assertEquals(1.0, p.inStart, 1e-9)
        assertEquals(0.0, ((p.start - 200.0) / 0.5) % 4, 1e-9) // on a bar
        assertTrue(p.start + p.length <= 238.0)
        assertEquals("dj", p.volume); assertEquals("swap", p.eq)
    }

    @Test fun noMixPointsFades() {
        val p = plan(t(1, duration = 200.0), t(2), null, 200.0)
        assertEquals("fade", p.style)
        assertFalse(p.beatmatch)
        assertEquals(8.0, p.length, 1e-9)
        assertEquals(192.0, p.start, 1e-9)
        assertEquals(1.0, p.rate, 0.0)
    }

    @Test fun cutHasNoOverlap() {
        val p = plan(t(1, duration = 200.0), t(2), JsonPrimitive("cut"), 200.0)
        assertEquals(0.0, p.length, 0.0)
        assertEquals(200.0, p.start, 1e-9)
    }

    @Test fun equalPowerCurves() {
        val smooth = Plan(style = "fade", start = 0.0, length = 8.0, volume = "smooth")
        assertEquals(0.7071, levels(smooth, "in", 4.0).gain, 1e-3)
        assertEquals(0.7071, levels(smooth, "out", 4.0).gain, 1e-3)
        assertEquals(0.0, levels(smooth, "in", 0.0).gain, 1e-9)
        assertEquals(1.0, levels(smooth, "in", 8.0).gain, 1e-9)
        val dj = Plan(style = "blend", start = 0.0, length = 8.0, volume = "dj", eq = "swap", filter = "none")
        assertEquals(1.0, levels(dj, "in", 4.0).gain, 1e-9)
        assertEquals(1.0, levels(dj, "out", 4.0).gain, 1e-9)
        assertEquals(-26.0, levels(dj, "in", 1.0).bassDb, 0.0)
        assertEquals(0.0, levels(dj, "in", 5.0).bassDb, 0.0)
        assertEquals(-26.0, levels(dj, "out", 5.0).bassDb, 0.0)
        val rise = Plan(style = "rise", start = 0.0, length = 4.0, filter = "rise")
        assertEquals(30.0, levels(rise, "out", 0.0).highpassHz!!, 1e-6)
        assertEquals(1400.0, levels(rise, "out", 4.0).highpassHz!!, 1e-6)
        assertNull(levels(rise, "in", 2.0).highpassHz)
    }

    @Test fun crossfadeSkipsAlbumsInOrder() {
        val a = t(1, album = 7); val b = t(2, album = 7); val c = t(3, album = 8)
        assertNull(crossfadePlan(8, albums = false, shuffle = false, a, b, 240.0))
        assertEquals(8.0, crossfadePlan(8, albums = false, shuffle = true, a, b, 240.0)!!.length, 0.0)
        assertEquals(8.0, crossfadePlan(8, albums = true, shuffle = false, a, b, 240.0)!!.length, 0.0)
        val short = crossfadePlan(12, albums = false, shuffle = false, a, c, 30.0)!!
        assertEquals(10.0, short.length, 1e-9) // a third of the song at most
        assertEquals(20.0, short.start, 1e-9)
        assertNull(crossfadePlan(0, albums = false, shuffle = false, a, c, 240.0))
    }
}
