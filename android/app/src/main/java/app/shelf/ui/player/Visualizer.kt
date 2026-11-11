package app.shelf.ui.player

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.MutableState
import androidx.compose.runtime.State
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import app.shelf.playback.SpectrumTap
import app.shelf.playback.smoothBands
import app.shelf.playback.spectrumBands
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.min
import kotlin.math.sin

private const val BANDS = 64

/**
 * The visualizer's levels, one per band (0..1), following the music every frame while [on]
 * (the player's audio processor only keeps samples while something's listening). When off or
 * paused, the bars settle back down.
 */
@Composable
fun rememberSpectrum(on: Boolean): State<FloatArray> {
    val levels: MutableState<FloatArray> = remember { mutableStateOf(FloatArray(BANDS)) }
    LaunchedEffect(on) {
        if (!on) {
            while (levels.value.any { it > 0f }) { withFrameNanos { }; levels.value = smoothBands(levels.value, FloatArray(BANDS)) }
            return@LaunchedEffect
        }
        SpectrumTap.listening = true
        try {
            while (true) {
                withFrameNanos { }
                val tap = SpectrumTap.shared
                val now = tap.snapshot(2048)?.let { spectrumBands(it, tap.sampleRate, BANDS) } ?: FloatArray(BANDS)
                levels.value = smoothBands(levels.value, now)
            }
        } finally { SpectrumTap.listening = false }
    }
    return levels
}

/** A ring of bars around this (round) thing, drawn behind it: lows at the top, highs at the bottom, mirrored. */
fun Modifier.spectrumRing(levels: State<FloatArray>?, color: Color): Modifier = if (levels == null) this else drawBehind {
    val v = levels.value
    if (v.all { it == 0f }) return@drawBehind
    val r = min(size.width, size.height) / 2 * 1.04f
    val len = r * 0.22f
    val stroke = maxOf(2f, r * 0.025f)
    val n = v.size * 2
    for (i in 0 until n) {
        val level = v[if (i < v.size) i else n - 1 - i]
        val a = -PI / 2 + i.toDouble() / n * 2 * PI
        val (cx, cy) = center
        val l = 2f + level * len
        drawLine(color.copy(alpha = 0.35f + 0.65f * level),
            Offset(cx + (cos(a) * r).toFloat(), cy + (sin(a) * r).toFloat()),
            Offset(cx + (cos(a) * (r + l)).toFloat(), cy + (sin(a) * (r + l)).toFloat()),
            strokeWidth = stroke, cap = StrokeCap.Round)
    }
}
