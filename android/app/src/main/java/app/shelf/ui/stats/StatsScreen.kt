package app.shelf.ui.stats

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.shelf.R
import app.shelf.data.ShelfApi
import app.shelf.playback.PlayContext
import app.shelf.ui.SignedOutHandler
import app.shelf.ui.browse.OnPlay
import app.shelf.ui.common.CoverCard
import app.shelf.ui.common.LoadContent
import app.shelf.ui.common.SectionTitle
import app.shelf.ui.common.Shelf
import app.shelf.ui.common.TrackRow
import app.shelf.ui.common.fmtTime
import app.shelf.ui.common.plural
import app.shelf.ui.common.rememberLoad
import app.shelf.ui.covers.CaseCover
import app.shelf.ui.covers.albumColor
import app.shelf.ui.theme.Shelf as Theme

private val WEEKDAYS = listOf("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

/** Your listening: totals, streak, top artists, songs, albums and genres, when you listen, and On this day. */
@Composable
fun StatsScreen(api: ShelfApi, onPlay: OnPlay, onAlbum: (Int) -> Unit, onArtist: (String) -> Unit, onWrapped: (Int) -> Unit,
                onBack: () -> Unit, signedOut: SignedOutHandler) {
    var period by rememberSaveable { mutableStateOf("year") }
    val (state, retry) = rememberLoad("stats:$period") { api.stats(period) }
    LoadContent(state, retry, signedOut, onBack) { s ->
        val ctx = PlayContext("Your top songs", "stats")
        LazyColumn(Modifier.fillMaxSize()) {
            item {
                Row(Modifier.statusBarsPadding().padding(4.dp), verticalAlignment = Alignment.CenterVertically) {
                    IconButton(onClick = onBack) { Icon(painterResource(R.drawable.ic_back), "Back", tint = Theme.colors.ink) }
                    Text("Your listening", style = MaterialTheme.typography.headlineSmall, color = Theme.colors.ink)
                }
                Text(if (s.plays == 0) "Nothing played in this period yet"
                     else "${hoursText(s.minutes)} of music: ${plural(s.plays, "play")} of ${plural(s.songs, "song")} by ${plural(s.artists, "artist")}.",
                    style = MaterialTheme.typography.bodyLarge, color = Theme.colors.ink2, modifier = Modifier.padding(horizontal = 16.dp))
                s.years.firstOrNull()?.let { year ->
                    Button(onClick = { onWrapped(year) }, modifier = Modifier.padding(16.dp, 12.dp, 16.dp, 4.dp),
                        colors = ButtonDefaults.buttonColors(containerColor = Theme.colors.cobalt, contentColor = Theme.colors.cobaltInk)) {
                        Icon(painterResource(R.drawable.ic_sparkle), null, Modifier.padding(end = 8.dp))
                        Text("Your $year Wrapped")
                    }
                }
                val periods = listOf("month", "year", "all") + s.years.drop(1).map { it.toString() }
                LazyRow(contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    items(periods) { p ->
                        FilterChip(selected = p == period, onClick = { period = p }, label = { Text(PERIOD_LABEL[p] ?: p) },
                            colors = FilterChipDefaults.filterChipColors(selectedContainerColor = Theme.colors.ink, selectedLabelColor = Theme.colors.tray,
                                labelColor = Theme.colors.ink))
                    }
                }
                if (s.currentStreak > 0 || s.longestStreak > 0) Text(streakText(s.currentStreak, s.longestStreak, period),
                    style = MaterialTheme.typography.bodyLarge, color = Theme.colors.ink, modifier = Modifier.padding(16.dp, 8.dp))
            }
            if (s.plays == 0) return@LazyColumn
            item { SectionTitle("Top artists") }
            itemsIndexed(s.topArtists) { i, a ->
                Row(Modifier.fillMaxWidth().clickable { onArtist(a.name) }.padding(horizontal = 16.dp, vertical = 9.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text("${i + 1}", color = Theme.colors.ink2, modifier = Modifier.width(30.dp))
                    Text(a.name, style = MaterialTheme.typography.titleMedium, color = Theme.colors.ink, maxLines = 1, overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.weight(1f))
                    Text(plural(a.plays, "play"), style = MaterialTheme.typography.bodyMedium, color = Theme.colors.ink2)
                }
            }
            item {
                SectionTitle("When you listen")
                Text("You’re ${listenerKind(s.hours).second}.", style = MaterialTheme.typography.bodyMedium, color = Theme.colors.ink2,
                    modifier = Modifier.padding(horizontal = 16.dp))
                Bars(s.hours, listOf("0", "6", "12", "18"), 92)
                Bars(s.weekdays, WEEKDAYS, 70, centred = true)
                s.busiestDay?.let { d ->
                    val day = runCatching { java.time.LocalDate.parse(d.date).format(java.time.format.DateTimeFormatter.ofPattern("EEEE d MMMM yyyy")) }.getOrDefault(d.date)
                    Text("Busiest day: $day, ${plural(d.plays, "play")}.", style = MaterialTheme.typography.bodyMedium, color = Theme.colors.ink2,
                        modifier = Modifier.padding(horizontal = 16.dp))
                }
            }
            item {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    SectionTitle("Top songs", Modifier.weight(1f))
                    TextButton(onClick = { onPlay(s.topSongs, 0, ctx) }) { Text("Play them", color = Theme.colors.cobalt) }
                }
            }
            itemsIndexed(s.topSongs) { i, t ->
                TrackRow(null, t.title, "${plural(t.plays, "play")}, ${t.artist}", fmtTime(t.duration), { onPlay(s.topSongs, i, ctx) },
                    coverUrl = api.coverUrl(t.albumId, t.cover, 160), coverColor = albumColor(null, t.album), track = t)
            }
            if (s.topAlbums.isNotEmpty()) item {
                SectionTitle("Top albums")
                Shelf(s.topAlbums) { a ->
                    CoverCard(a.title, plural(a.plays, "play"), onClick = { onAlbum(a.id) }) {
                        CaseCover(api.coverUrl(a.id, a.cover, 320), a.title, albumColor(a.color, a.title))
                    }
                }
            }
            if (s.topGenres.isNotEmpty()) item {
                SectionTitle("Top genres")
                Text(s.topGenres.joinToString(", ") { g -> "${g.name.split(' ').joinToString(" ") { it.replaceFirstChar(Char::uppercase) }} (${g.plays})" },
                    style = MaterialTheme.typography.bodyLarge, color = Theme.colors.ink, modifier = Modifier.padding(horizontal = 16.dp))
            }
            if (s.newArtists.isNotEmpty() && period != "all") item {
                SectionTitle("New to you")
                Text("${plural(s.newArtists.size, "artist")} you hadn’t played before: ${s.newArtists.take(12).joinToString(", ")}" +
                    if (s.newArtists.size > 12) " and more." else ".",
                    style = MaterialTheme.typography.bodyMedium, color = Theme.colors.ink2, modifier = Modifier.padding(horizontal = 16.dp))
            }
            if (s.onThisDay.isNotEmpty()) {
                item { SectionTitle("On this day, a year ago") }
                itemsIndexed(s.onThisDay) { i, t ->
                    TrackRow(null, t.title, t.artist, fmtTime(t.duration), { onPlay(s.onThisDay, i, PlayContext("On this day", "stats")) },
                        coverUrl = api.coverUrl(t.albumId, t.cover, 160), coverColor = albumColor(null, t.album), track = t)
                }
            }
            item { Spacer(Modifier.height(24.dp)) }
        }
    }
}

/** Plays by hour or weekday as bars, the busiest one in the accent colour. Each label sits under its share of the bars
 * (four labels under 24 hours: 0, 6, 12, 18). */
@Composable
private fun Bars(counts: List<Int>, labels: List<String>, heightDp: Int, centred: Boolean = false) {
    val top = (counts.maxOrNull() ?: 0).coerceAtLeast(1)
    val peak = counts.indexOf(counts.maxOrNull() ?: 0)
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp)) {
        Row(Modifier.fillMaxWidth().height(heightDp.dp), horizontalArrangement = Arrangement.spacedBy(3.dp), verticalAlignment = Alignment.Bottom) {
            counts.forEachIndexed { i, n ->
                Box(Modifier.weight(1f).fillMaxHeight((n.toFloat() / top).coerceAtLeast(0.02f)).clip(RoundedCornerShape(topStart = 3.dp, topEnd = 3.dp))
                    .background(if (i == peak && n > 0) Theme.colors.cobalt else Theme.colors.ink.copy(alpha = 0.22f)))
            }
        }
        Row(Modifier.fillMaxWidth()) {
            labels.forEach {
                Text(it, style = MaterialTheme.typography.labelSmall, color = Theme.colors.ink2, maxLines = 1, modifier = Modifier.weight(1f),
                    textAlign = if (centred) androidx.compose.ui.text.style.TextAlign.Center else androidx.compose.ui.text.style.TextAlign.Start)
            }
        }
    }
}
