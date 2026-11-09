package app.shelf.ui.covers

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.graphics.drawscope.scale
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.shelf.ui.theme.Archivo
import app.shelf.ui.theme.Caveat
import coil3.compose.AsyncImage

/**
 * A mix as a cassette: a label hand-written in Caveat with a stripe in the mix's [color], lying
 * a little askew on the card insert that shows its albums along the top. [rolling]: the reels
 * turn (while the mix plays). The same design as the web app's .mix-tape.
 */
@Composable
fun TapeCover(name: String, color: Color, covers: List<String>, modifier: Modifier = Modifier, rolling: Boolean = false) {
    val shape = RoundedCornerShape(6.dp)
    BoxWithConstraints(
        modifier.aspectRatio(1f).shadow(4.dp, shape).clip(shape)
            .background(Brush.verticalGradient(listOf(Color.White.copy(alpha = .16f), Color.Black.copy(alpha = .14f))))
            .background(color),
    ) {
        val w = maxWidth
        // the card insert: up to four of the mix's albums along the top
        Row(Modifier.padding(start = w * 0.06f, end = w * 0.06f, top = w * 0.07f).fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(w * 0.024f)) {
            covers.take(4).forEach { url ->
                AsyncImage(url, null, contentScale = ContentScale.Crop,
                    modifier = Modifier.weight(1f).aspectRatio(1f).shadow(2.dp, RoundedCornerShape(w * 0.012f)).clip(RoundedCornerShape(w * 0.012f)))
            }
        }
        // the tape
        val angle by if (rolling) rememberInfiniteTransition(label = "reels")
            .animateFloat(0f, 360f, infiniteRepeatable(tween(2400, easing = LinearEasing), RepeatMode.Restart), label = "reel")
        else androidx.compose.runtime.remember { androidx.compose.runtime.mutableFloatStateOf(0f) }
        Box(Modifier.align(Alignment.BottomStart).offset(x = w * 0.06f, y = -(w * 0.05f)).padding(0.dp)
            .fillMaxWidth(0.88f).aspectRatio(200f / 126f).rotate(-3.5f).shadow(8.dp, RoundedCornerShape(w * 0.04f), clip = false)) {
            val measurer = rememberTextMeasurer()
            Canvas(Modifier.fillMaxSize()) { drawTape(color, angle, measurer) }
            val len = name.length
            val size = when { len > 30 -> 0.084f; len > 14 -> 0.105f; else -> 0.14f }
            // The label: from the top of the tape down to the writing line (y 41 of 126), written on it.
            Box(Modifier.fillMaxWidth().fillMaxHeight(0.335f)
                .padding(start = w * 0.88f * 0.12f, end = w * 0.88f * (if (len > 30) 0.17f else 0.09f)).rotate(-1f),
                contentAlignment = Alignment.BottomStart) {
                Text(name, color = Color(0xff1d2a5c), fontFamily = Caveat, fontWeight = FontWeight.Bold,
                    fontSize = (w.value * size).sp,
                    lineHeight = if (len > 30) (w.value * size * 1.0f).sp else androidx.compose.ui.unit.TextUnit.Unspecified,
                    maxLines = if (len > 30) 2 else 1, overflow = TextOverflow.Ellipsis, softWrap = len > 30)
            }
        }
    }
}

/** The cassette, drawn in the web app's 200×126 viewBox and scaled to fit. */
private fun DrawScope.drawTape(color: Color, angle: Float, measurer: androidx.compose.ui.text.TextMeasurer) {
    val k = size.width / 200f
    scale(k, k, pivot = Offset.Zero) {
        drawRoundRect(Color(0xff25272e), Offset(1f, 1f), Size(198f, 124f), CornerRadius(9f))
        drawRoundRect(Color.White.copy(alpha = .08f), Offset(1f, 1f), Size(198f, 124f), CornerRadius(9f), style = Stroke(1f))
        drawPath(Path().apply { moveTo(40f, 125f); lineTo(49f, 97f); lineTo(151f, 97f); lineTo(160f, 125f); close() }, Color(0xff30333b))
        listOf(Offset(9f, 9f), Offset(191f, 9f), Offset(9f, 117f), Offset(191f, 117f)).forEach { drawCircle(Color(0xff7d8290), 3f, it) }
        drawCircle(Color(0xff7d8290), 2.6f, Offset(100f, 117f))
        drawCircle(Color(0xff121317), 4.2f, Offset(64f, 111f))
        drawCircle(Color(0xff121317), 4.2f, Offset(136f, 111f))
        drawRoundRect(Color(0xff121317), Offset(93f, 101f), Size(14f, 7f), CornerRadius(2f))
        drawRoundRect(Color(0xfff3eedf), Offset(13f, 8f), Size(174f, 82f), CornerRadius(4f))
        drawRect(color, Offset(13f, 48f), Size(174f, 30f))
        drawLine(Color(0x38281e14), Offset(24f, 41f), Offset(176f, 41f), 0.8f)
        // Text sizes are in viewBox units: this drawing is already scaled by k.
        drawText(measurer, "A", Offset(18f, 12f), TextStyle(color = Color(0x8c281e14), fontFamily = Archivo, fontWeight = FontWeight.ExtraBold, fontSize = 11f.toSp()))
        drawText(measurer, "C90", Offset(164f, 14f), TextStyle(color = Color(0x66281e14), fontFamily = Archivo, fontWeight = FontWeight.Bold, fontSize = 7f.toSp(), letterSpacing = 0.4f.toSp()))
        drawRoundRect(Color(0xff17181d), Offset(48f, 52f), Size(104f, 22f), CornerRadius(11f))
        drawCircle(Color(0xff4b3427), 10.5f, Offset(72f, 63f))
        drawCircle(Color(0xff4b3427), 7.2f, Offset(128f, 63f))
        for (cx in listOf(72f, 128f)) {
            rotate(angle, pivot = Offset(cx, 63f)) {
                drawCircle(Color(0xffe8e3d6), 5.6f, Offset(cx, 63f))
                for (i in 0 until 6) {
                    val a = Math.toRadians(i * 60.0)
                    val dx = kotlin.math.sin(a).toFloat()
                    val dy = -kotlin.math.cos(a).toFloat()
                    drawLine(Color(0xff17181d), Offset(cx + dx * 2.4f, 63f + dy * 2.4f), Offset(cx + dx * 4.4f, 63f + dy * 4.4f), 1.6f)
                }
            }
        }
        drawRoundRect(Color.White.copy(alpha = .07f), Offset(48f, 52f), Size(104f, 9f), CornerRadius(4.5f))
    }
}
