package app.shelf.ui.player

import android.provider.Settings
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.CompositingStrategy
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import app.shelf.settings.LocalSettings
import coil3.compose.AsyncImage

/**
 * The disc beside the case on Now Playing, turning while the music plays (unless the phone asks
 * for less motion): a silver CD, or with the vinyl setting, a black record with the album art
 * on its label, as on the web app.
 */
@Composable
fun Disc(labelUrl: String?, spinning: Boolean, modifier: Modifier = Modifier, labelColor: Color = Color(0xffc94a3a)) {
    val vinyl = LocalSettings.current.format == "vinyl"
    val reduceMotion = Settings.Global.getFloat(LocalContext.current.contentResolver, Settings.Global.ANIMATOR_DURATION_SCALE, 1f) == 0f
    val turn = if (vinyl) 1800 else 7000 // a record turns at 33⅓ a minute; a CD, slowly enough to see
    val angle by if (spinning && !reduceMotion) rememberInfiniteTransition(label = "disc")
        .animateFloat(0f, 360f, infiniteRepeatable(tween(turn, easing = LinearEasing), RepeatMode.Restart), label = "spin")
    else remember { mutableFloatStateOf(0f) }
    if (vinyl) Record(labelUrl, labelColor, angle, modifier) else Cd(angle, modifier)
}

@Composable
private fun Cd(angle: Float, modifier: Modifier) {
    Canvas(modifier.testTag("disc-cd").rotate(angle)) {
        val r = size.minDimension / 2
        drawCircle(Brush.sweepGradient(listOf(Color(0xffd9dde4), Color(0xfff2f4f8), Color(0xffbfc6d2), Color(0xffe9ecf1), Color(0xffcfd5de), Color(0xffd9dde4))), r)
        for (k in 1..6) drawCircle(Color.Black.copy(alpha = .05f), r * (0.38f + k * 0.09f), style = Stroke(1f))
        drawCircle(Color(0xff9aa2b0), r * 0.18f)
        drawCircle(Color(0xffe6e9ef), r * 0.07f)
        drawCircle(Color.White.copy(alpha = .35f), r * 0.98f, Offset(center.x, center.y), style = Stroke(2f))
    }
}

private const val LABEL = 0.34f // the label's radius, as a share of the record's

@Composable
private fun Record(labelUrl: String?, labelColor: Color, angle: Float, modifier: Modifier) {
    Box(modifier.testTag("disc-record").graphicsLayer(compositingStrategy = CompositingStrategy.Offscreen), contentAlignment = Alignment.Center) {
        // The record and its label turn together.
        Box(Modifier.fillMaxSize().rotate(angle), contentAlignment = Alignment.Center) {
            Canvas(Modifier.fillMaxSize()) {
                val r = size.minDimension / 2
                drawCircle(Color(0xff1c1c1f), r)
                // Fine grooves, with the gaps between songs and a smooth run-out band by the label.
                var g = r * 0.43f
                val step = 1.3f * density
                while (g < r * 0.965f) { drawCircle(Color(0xff121214), g, style = Stroke(.55f * density)); g += step }
                for (gap in listOf(0.58f, 0.72f, 0.85f)) drawCircle(Color(0xff26262a), r * gap, style = Stroke(r * 0.008f))
                drawCircle(Color(0xff161618), r * 0.395f, style = Stroke(r * 0.07f))
                drawCircle(Color.White.copy(alpha = .05f), r * 0.43f, style = Stroke(r * 0.005f))
                drawCircle(Color.White.copy(alpha = .16f), r * 0.976f, style = Stroke(r * 0.01f))
                drawCircle(Color.Black.copy(alpha = .5f), r * 0.993f, style = Stroke(r * 0.014f))
                drawCircle(labelColor, r * LABEL)
            }
            if (labelUrl != null) AsyncImage(labelUrl, null, contentScale = ContentScale.Crop,
                modifier = Modifier.fillMaxWidth(LABEL * 2).aspectRatio(1f).clip(CircleShape))
        }
        Canvas(Modifier.fillMaxSize()) {
            val r = size.minDimension / 2
            // The label's edge, then the light on the vinyl: a bow-tie of reflection that stays put while the record turns.
            drawCircle(Color.Black.copy(alpha = .35f), r * LABEL, style = Stroke(1f * density))
            drawCircle(Brush.sweepGradient(0f to Color.Transparent, .06f to Color.Transparent, .1f to Color.White.copy(alpha = .13f), .15f to Color.Transparent,
                .56f to Color.Transparent, .6f to Color.White.copy(alpha = .13f), .65f to Color.Transparent, 1f to Color.Transparent),
                radius = r * 0.705f, style = Stroke(r * 0.55f))
            // The spindle hole goes right through.
            drawCircle(Color.Black, r * 0.028f, blendMode = BlendMode.Clear)
        }
    }
}
