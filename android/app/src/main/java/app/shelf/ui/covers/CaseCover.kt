package app.shelf.ui.covers

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.shelf.ui.theme.Archivo
import coil3.compose.AsyncImage

/**
 * An album as it sits on the shelf: a CD jewel case (the clear hinge on the left and light
 * catching the front), or with [vinyl], a record sleeve (matte card with the record's ring
 * pressed through). With no cover art, the album's colour with its title printed on it.
 * The same look as the web app's .case.
 */
@Composable
fun CaseCover(url: String?, title: String, color: Color, modifier: Modifier = Modifier,
              vinyl: Boolean = app.shelf.settings.LocalSettings.current.format == "vinyl") {
    val shape = RoundedCornerShape(if (vinyl) 1.5.dp else 3.dp)
    BoxWithConstraints(
        modifier
            .aspectRatio(1f)
            .shadow(if (vinyl) 6.dp else 4.dp, shape)
            .clip(shape)
            .background(color)
            .drawWithContent {
                drawContent()
                if (vinyl) drawSleeve() else drawJewelCase(small = size.width < 64.dp.toPx())
            },
    ) {
        val w = maxWidth
        if (url != null) {
            AsyncImage(model = url, contentDescription = null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
        } else if (w >= 64.dp) {
            Box(Modifier.fillMaxSize().padding(start = w * 0.16f, top = w * 0.14f, end = w * 0.10f, bottom = w * 0.10f),
                contentAlignment = Alignment.BottomStart) {
                Text(title, color = Color.White.copy(alpha = 0.92f), fontFamily = Archivo, fontWeight = FontWeight.ExtraBold,
                    fontSize = (w.value * 0.085f).coerceIn(11f, 22f).sp, lineHeight = (w.value * 0.09f).coerceIn(12f, 23f).sp,
                    maxLines = 4, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}

/** The hinge (the clear spine) and the gloss across the front of a jewel case. */
private fun DrawScope.drawJewelCase(small: Boolean) {
    val w = size.width
    val h = size.height
    // gloss: light catching the front
    drawRect(Brush.linearGradient(0f to Color.White.copy(alpha = .20f), .34f to Color.White.copy(alpha = .05f), .35f to Color.Transparent,
        start = Offset(0f, 0f), end = Offset(w, h * 0.53f)))
    // hinge
    val hw = w * (if (small) 0.09f else 0.075f)
    drawRect(Brush.horizontalGradient(
        0f to Color.White.copy(alpha = .42f), .18f to Color.White.copy(alpha = .10f), .30f to Color.Black.copy(alpha = .22f),
        .46f to Color.White.copy(alpha = .16f), .70f to Color.White.copy(alpha = .04f), 1f to Color.Black.copy(alpha = .28f),
        startX = 0f, endX = hw), size = size.copy(width = hw))
    drawLine(Color.White.copy(alpha = .22f), Offset(hw, 0f), Offset(hw, h), 1f)
    drawLine(Color.Black.copy(alpha = .18f), Offset(hw + 1f, 0f), Offset(hw + 1f, h), 1f)
    // edges of the plastic
    drawRect(Color.White.copy(alpha = .18f), style = Stroke(1.5f))
}

/** A record sleeve: ring wear where the record presses through, and the open side on the right. */
private fun DrawScope.drawSleeve() {
    val w = size.width
    val c = center
    drawCircle(Color.White.copy(alpha = .10f), radius = w * 0.462f, center = c, style = Stroke(w * 0.012f))
    drawCircle(Color.White.copy(alpha = .05f), radius = w * 0.150f, center = c, style = Stroke(w * 0.008f))
    drawRect(Brush.horizontalGradient(.976f to Color.Transparent, .986f to Color.Black.copy(alpha = .14f), .994f to Color.White.copy(alpha = .12f),
        startX = 0f, endX = w))
    drawRect(Color.Black.copy(alpha = .12f), style = Stroke(1.5f))
}
