package app.shelf.ui.player

import android.provider.Settings
import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.snap
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.size
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
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import app.shelf.data.Track
import app.shelf.settings.LocalSettings
import app.shelf.ui.covers.CaseCover
import app.shelf.ui.covers.fallbackColor
import coil3.compose.AsyncImage

/**
 * The disc beside the case on Now Playing, turning while the music plays (unless the phone asks
 * for less motion): a silver CD, or with the vinyl setting, a black record with the album art
 * on its label, as on the web app.
 */
@Composable
private fun reduceMotion() = Settings.Global.getFloat(LocalContext.current.contentResolver, Settings.Global.ANIMATOR_DURATION_SCALE, 1f) == 0f

/**
 * Now Playing's cover: the case (or sleeve) with its disc. A CD sits half out to the right. A
 * record, as on the web app, slides out of its sleeve when the music plays (the sleeve moving
 * left to make room) and the tonearm swings onto it; on pause the arm lifts and it goes back in.
 */
@Composable
internal fun Deck(t: Track, url: String?, playing: Boolean, modifier: Modifier = Modifier,
                  levels: androidx.compose.runtime.State<FloatArray>? = null, ringColor: Color = Color.White) {
    val color = fallbackColor(t.album)
    if (LocalSettings.current.format != "vinyl") {
        BoxWithConstraints(modifier, contentAlignment = Alignment.CenterStart) {
            val case = maxWidth * 0.86f
            Disc(url, playing, Modifier.size(case * 0.94f).offset(x = maxWidth - case * 0.94f, y = case * 0.03f).spectrumRing(levels, ringColor), labelColor = color)
            CaseCover(url, t.album, color, Modifier.size(case))
        }
        return
    }
    val still = reduceMotion()
    val ease = CubicBezierEasing(.2f, .8f, .2f, 1f)
    val out by animateFloatAsState(if (playing) 1f else 0f, if (still) snap() else tween(900, easing = ease), label = "out")
    // The arm moves once the record is out, and lifts straight away on pause.
    val arm by animateFloatAsState(if (playing) 24f else 4f,
        if (still) snap() else tween(700, delayMillis = if (playing) 750 else 0, easing = CubicBezierEasing(.3f, .6f, .3f, 1f)), label = "arm")
    BoxWithConstraints(modifier, contentAlignment = Alignment.CenterStart) {
        // With the record out, everything from the sleeve's left edge to the arm's pivot spans
        // 1.41 decks; size the deck so that fits, centred.
        val deck = maxWidth * 0.69f
        val disc = deck * 0.89f
        val rest = (maxWidth - deck * 1.412f) / 2 + deck * 0.17f
        Box(Modifier.offset(x = rest - deck * 0.17f * out).size(deck)) {
            Box(Modifier.offset(x = deck * 0.055f + disc * 0.46f * out, y = deck * 0.055f).size(disc)) {
                Disc(url, playing, Modifier.fillMaxSize().spectrumRing(levels, ringColor), labelColor = color)
                Tonearm(arm, Modifier.fillMaxSize().graphicsLayer { alpha = out })
            }
            CaseCover(url, t.album, color, Modifier.fillMaxSize())
        }
    }
}

/** The tonearm, drawn in the record's box: its pivot just off the top right, the arm [angle] degrees from hanging straight down. */
@Composable
private fun Tonearm(angle: Float, modifier: Modifier) {
    Canvas(modifier.testTag("tonearm")) {
        val w = size.width; val h = size.height
        val pivot = Offset(w * 1.03f, h * 0.03f)
        val armW = w * 0.013f; val armL = h * 0.72f
        val headW = armW * 3.8f; val headH = armL * 0.07f
        rotate(angle, pivot) {
            // shadow, then the arm and the head at its end
            val shadow = Offset(w * 0.006f, w * 0.012f)
            drawRoundRect(Color.Black.copy(alpha = .22f), pivot + shadow - Offset(armW / 2, 0f), Size(armW, armL), CornerRadius(armW / 2))
            drawRoundRect(Brush.horizontalGradient(listOf(Color(0xff8c929a), Color(0xffeef0f3), Color(0xff9aa0a8)), pivot.x - armW / 2, pivot.x + armW / 2),
                pivot - Offset(armW / 2, 0f), Size(armW, armL), CornerRadius(armW / 2))
            val head = Offset(pivot.x - headW / 2, pivot.y + armL - headH * 0.3f)
            drawRoundRect(Color.Black.copy(alpha = .3f), head + shadow, Size(headW, headH), CornerRadius(headH * 0.25f))
            drawRoundRect(Brush.verticalGradient(listOf(Color(0xff3a3d43), Color(0xff1c1e22)), head.y, head.y + headH), head, Size(headW, headH), CornerRadius(headH * 0.25f))
        }
        val r = w * 0.035f
        drawCircle(Color.Black.copy(alpha = .3f), r, pivot + Offset(0f, w * 0.008f))
        drawCircle(Brush.radialGradient(listOf(Color(0xfff2f3f5), Color(0xff9aa0a8), Color(0xff5d636b)), pivot - Offset(r * .3f, r * .4f), r * 1.4f), r, pivot)
    }
}

@Composable
fun Disc(labelUrl: String?, spinning: Boolean, modifier: Modifier = Modifier, labelColor: Color = Color(0xffc94a3a)) {
    val vinyl = LocalSettings.current.format == "vinyl"
    val reduceMotion = reduceMotion()
    val turn = if (vinyl) 1800 else 7000 // a record turns at 33⅓ a minute; a CD, slowly enough to see
    val spin = LocalSettings.current.spinDisc
    val angle by if (spinning && spin && !reduceMotion) rememberInfiniteTransition(label = "disc")
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

private const val LABEL = 0.17f // the label's radius, as a share of the record's (a third of its width, as on a real LP)

@Composable
private fun Record(labelUrl: String?, labelColor: Color, angle: Float, modifier: Modifier) {
    Box(modifier.testTag("disc-record").graphicsLayer(compositingStrategy = CompositingStrategy.Offscreen), contentAlignment = Alignment.Center) {
        // The record and its label turn together.
        Box(Modifier.fillMaxSize().rotate(angle), contentAlignment = Alignment.Center) {
            Canvas(Modifier.fillMaxSize()) {
                val r = size.minDimension / 2
                drawCircle(Color(0xff1c1c1f), r)
                // Fine grooves, with the gaps between songs and a smooth run-out band by the label.
                var g = r * 0.26f
                val step = 1.3f * density
                while (g < r * 0.965f) { drawCircle(Color(0xff121214), g, style = Stroke(.55f * density)); g += step }
                for (gap in listOf(0.44f, 0.6f, 0.77f)) drawCircle(Color(0xff26262a), r * gap, style = Stroke(r * 0.008f))
                drawCircle(Color(0xff161618), r * 0.215f, style = Stroke(r * 0.09f))
                drawCircle(Color.White.copy(alpha = .05f), r * 0.26f, style = Stroke(r * 0.005f))
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
                radius = r * 0.63f, style = Stroke(r * 0.7f))
            // The spindle hole goes right through.
            drawCircle(Color.Black, r * 0.028f, blendMode = BlendMode.Clear)
        }
    }
}
