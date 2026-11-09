package app.shelf.ui.common

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import app.shelf.R
import app.shelf.ui.covers.CaseCover
import app.shelf.ui.theme.Shelf
import coil3.compose.AsyncImage

/** A section heading on a page ("Made for you"). */
@Composable
fun SectionTitle(text: String, modifier: Modifier = Modifier) {
    Text(text, style = MaterialTheme.typography.headlineSmall, color = Shelf.colors.ink, modifier = modifier.padding(horizontal = 16.dp, vertical = 10.dp))
}

/** A horizontal shelf of things (albums, tapes). */
@Composable
fun <T> Shelf(items: List<T>, item: @Composable (T) -> Unit) {
    LazyRow(contentPadding = PaddingValues(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(14.dp)) {
        items(items) { item(it) }
    }
}

/** A cover with a title and a line under it, as on a shelf. */
@Composable
fun CoverCard(title: String, subtitle: String?, width: Dp = 148.dp, onClick: () -> Unit, cover: @Composable () -> Unit) {
    Column(Modifier.width(width).clip(RoundedCornerShape(8.dp)).clickable(onClick = onClick).padding(bottom = 4.dp)) {
        Box(Modifier.size(width)) { cover() }
        Spacer(Modifier.height(8.dp))
        Text(title, style = MaterialTheme.typography.titleSmall, color = Shelf.colors.ink, maxLines = 1, overflow = TextOverflow.Ellipsis)
        if (subtitle != null) Text(subtitle, style = MaterialTheme.typography.bodySmall, color = Shelf.colors.ink2, maxLines = 2, overflow = TextOverflow.Ellipsis)
    }
}

/** A credit with each artist as their own link ("Aerosmith & Yungblud": two links), keeping the credit's own wording. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ArtistLinks(credit: String, names: List<String>, onArtist: (String) -> Unit, modifier: Modifier = Modifier, style: androidx.compose.ui.text.TextStyle = MaterialTheme.typography.titleMedium) {
    val list = names.ifEmpty { listOf(credit) }
    // Pieces of the credit: a link per name found in it (any case), with the text between.
    val pieces = mutableListOf<Pair<String, String?>>()
    var pos = 0
    val low = credit.lowercase()
    var ok = true
    for (n in list) {
        val i = low.indexOf(n.lowercase(), pos)
        if (i < 0) { ok = false; break }
        if (i > pos) pieces += credit.substring(pos, i) to null
        pieces += credit.substring(i, i + n.length) to n
        pos = i + n.length
    }
    if (!ok || list.size == 1) {
        pieces.clear()
        if (list.size == 1) pieces += credit to list[0]
        else list.forEachIndexed { i, n -> if (i > 0) pieces += ", " to null; pieces += n to n }
    } else if (pos < credit.length) pieces += credit.substring(pos) to null
    FlowRow(modifier) {
        pieces.forEach { (text, name) ->
            if (name == null) Text(text, style = style, color = Shelf.colors.ink2)
            else Text(text, style = style, color = Shelf.colors.ink, modifier = Modifier.clickable { onArtist(name) })
        }
    }
}

/** One song in a list: number (or cover), title, artist, length. */
@Composable
fun TrackRow(number: String?, title: String, subtitle: String?, length: String, onClick: () -> Unit, coverUrl: String? = null, coverColor: Color = Color.Gray) {
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 16.dp, vertical = 9.dp), verticalAlignment = Alignment.CenterVertically) {
        if (number != null) {
            Text(number, style = MaterialTheme.typography.bodyMedium, color = Shelf.colors.ink2, modifier = Modifier.width(30.dp))
        } else {
            CaseCover(coverUrl, title, coverColor, Modifier.size(46.dp))
            Spacer(Modifier.width(12.dp))
        }
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.titleMedium, color = Shelf.colors.ink, maxLines = 1, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.testTag("track-title"))
            if (subtitle != null) Text(subtitle, style = MaterialTheme.typography.bodySmall, color = Shelf.colors.ink2, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        Spacer(Modifier.width(10.dp))
        Text(length, style = MaterialTheme.typography.bodySmall, color = Shelf.colors.ink2)
    }
}

/** A playlist's cover: its first four albums in a grid (or one, or its name on a colour). */
@Composable
fun MosaicCover(urls: List<String>, title: String, color: Color, modifier: Modifier = Modifier) {
    val shape = RoundedCornerShape(6.dp)
    Box(modifier.aspectRatio(1f).shadow(4.dp, shape).clip(shape).background(color)) {
        when {
            urls.size >= 4 -> Column(Modifier.fillMaxSize()) {
                for (r in 0..1) Row(Modifier.weight(1f)) {
                    for (c in 0..1) AsyncImage(urls[r * 2 + c], null, contentScale = ContentScale.Crop, modifier = Modifier.weight(1f).fillMaxSize())
                }
            }
            urls.isNotEmpty() -> AsyncImage(urls[0], null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
            else -> CaseCover(null, title, color, Modifier.fillMaxSize())
        }
    }
}

/** Favourites: a blue heart on a silver disc face (Shelf's own; see the web's .liked-cover). */
@Composable
fun FavouritesCover(modifier: Modifier = Modifier) {
    val shape = RoundedCornerShape(6.dp)
    Box(modifier.aspectRatio(1f).shadow(4.dp, shape).clip(shape)
        .background(Brush.sweepGradient(listOf(Color(0xffdfe3ea), Color(0xfff4f6f9), Color(0xffc9cfd9), Color(0xffeef0f4), Color(0xffd3d8e0), Color(0xffdfe3ea)))),
        contentAlignment = Alignment.Center) {
        Icon(painterResource(R.drawable.ic_heart_filled), contentDescription = null, tint = Color(0xff2c4fd0), modifier = Modifier.fillMaxSize(0.46f))
    }
}

/** An artist's round photo or, without one, their first letter on a colour. */
@Composable
fun ArtistAvatar(url: String?, name: String, color: Color, modifier: Modifier = Modifier) {
    Box(modifier.aspectRatio(1f).clip(CircleShape).background(color), contentAlignment = Alignment.Center) {
        if (url != null) AsyncImage(url, null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
        else Text(name.take(1).uppercase(), style = MaterialTheme.typography.headlineSmall, color = Color.White)
    }
}

/** The page tint: the album's colour fading into the background, behind the top of a page. */
fun heroBrush(color: Color, tray: Color) = Brush.verticalGradient(listOf(color.copy(alpha = .62f), tray))
