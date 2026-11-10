package app.shelf.ui.stats

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.shelf.R
import app.shelf.data.ListeningStats
import app.shelf.data.ShelfApi
import app.shelf.playback.PlayContext
import app.shelf.ui.SignedOutHandler
import app.shelf.ui.browse.OnPlay
import app.shelf.ui.common.LoadContent
import app.shelf.ui.common.plural
import app.shelf.ui.common.rememberLoad
import kotlinx.coroutines.launch
import app.shelf.ui.theme.Shelf as Theme

private val CARD_COLOURS = listOf(
    Color(0xFF1C3FB7) to Color(0xFF0B1D5C), Color(0xFFB7261C) to Color(0xFF4D0B07), Color(0xFF0F7A5A) to Color(0xFF053023),
    Color(0xFF7A3FB7) to Color(0xFF2A0D4D), Color(0xFFB7781C) to Color(0xFF4D2E07),
)

/** One Wrapped card: a small line on top, a big one, then the details. */
private class Card(val kicker: String, val big: String?, val lines: List<String> = emptyList(), val play: Boolean = false)

private fun cards(s: ListeningStats, year: Int): List<Card> {
    if (s.plays == 0) return listOf(Card("$year", "Nothing played in $year", listOf("Play some music and come back.")))
    val title = { g: String -> g.split(' ').joinToString(" ") { it.replaceFirstChar(Char::uppercase) } }
    return listOfNotNull(
        Card("$year, in music", "You listened for ${hoursText(s.minutes)}.",
            listOf("${plural(s.plays, "play")} of ${plural(s.songs, "song")} by ${plural(s.artists, "artist")}.")),
        s.topArtists.firstOrNull()?.let { a ->
            Card("Your artist of the year", a.name, listOf("${plural(a.plays, "play")}, ${hoursText(a.minutes)} together.") +
                s.topArtists.drop(1).take(4).mapIndexed { i, o -> "${i + 2}. ${o.name}" })
        },
        s.topSongs.takeIf { it.isNotEmpty() }?.let { songs ->
            Card("Your top songs", null, songs.take(5).mapIndexed { i, t -> "${i + 1}. ${t.title}\n${t.artist}, ${plural(t.plays, "play")}" })
        },
        s.topGenres.firstOrNull()?.let { g ->
            Card("What it sounded like", title(g.name), s.topGenres.drop(1).take(3).takeIf { it.isNotEmpty() }
                ?.let { listOf("Then ${it.joinToString(", ") { o -> title(o.name) }}.") } ?: emptyList())
        },
        s.newArtists.takeIf { it.isNotEmpty() }?.let { n ->
            Card("New to you", "${plural(n.size, "artist")} you hadn’t played before",
                listOf(n.take(6).joinToString(", ") + if (n.size > 6) " and more." else "."))
        },
        Card("When you listened", "You’re ${listenerKind(s.hours).first}.", listOfNotNull(
            s.busiestDay?.let { d ->
                val day = runCatching { java.time.LocalDate.parse(d.date).format(java.time.format.DateTimeFormatter.ofPattern("EEEE d MMMM")) }.getOrDefault(d.date)
                "Your busiest day was $day, with ${plural(d.plays, "play")}."
            },
            s.longestStreak.takeIf { it > 1 }?.let { "Longest run: $it days in a row." },
        )),
        Card("That was $year", "Play your top songs", play = s.topSongs.isNotEmpty()),
    )
}

/** Your year in music, one card at a time: swipe, or Back and Next. */
@Composable
fun WrappedScreen(api: ShelfApi, year: Int, onPlay: OnPlay, onBack: () -> Unit, signedOut: SignedOutHandler) {
    val (state, retry) = rememberLoad("wrapped:$year") { api.stats(year.toString()) }
    LoadContent(state, retry, signedOut) { s ->
        val list = cards(s, year)
        val pager = rememberPagerState { list.size }
        val scope = rememberCoroutineScope()
        Column(Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding()) {
            Row(Modifier.padding(4.dp), verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = onBack) { Icon(painterResource(R.drawable.ic_back), "Back", tint = Theme.colors.ink) }
                Text("Your $year Wrapped", style = MaterialTheme.typography.titleLarge, color = Theme.colors.ink)
            }
            HorizontalPager(pager, Modifier.weight(1f).fillMaxWidth(), contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 16.dp),
                pageSpacing = 12.dp) { i ->
                val card = list[i]
                val (from, to) = CARD_COLOURS[i % CARD_COLOURS.size]
                Column(Modifier.fillMaxSize().padding(vertical = 8.dp).clip(RoundedCornerShape(18.dp))
                    .background(Brush.linearGradient(listOf(from, to))).padding(28.dp), verticalArrangement = Arrangement.Center) {
                    Text(card.kicker, color = Color.White.copy(alpha = 0.75f), style = MaterialTheme.typography.titleMedium)
                    card.big?.let { Text(it, color = Color.White, fontSize = 40.sp, lineHeight = 44.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(vertical = 8.dp)) }
                    card.lines.forEach { line ->
                        Text(line, color = Color.White.copy(alpha = 0.92f), style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(top = 6.dp))
                    }
                    if (card.play) {
                        Spacer(Modifier.height(16.dp))
                        Button(onClick = { onPlay(s.topSongs, 0, PlayContext("Your top songs of $year", "stats")) },
                            colors = ButtonDefaults.buttonColors(containerColor = Color.White, contentColor = from)) {
                            Icon(painterResource(R.drawable.ic_play), null, Modifier.padding(end = 6.dp)); Text("Play")
                        }
                    }
                }
            }
            Row(Modifier.fillMaxWidth().padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                TextButton(enabled = pager.currentPage > 0, onClick = { scope.launch { pager.animateScrollToPage(pager.currentPage - 1) } }) {
                    Text("Back", color = Theme.colors.ink)
                }
                Text("${pager.currentPage + 1} of ${list.size}", color = Theme.colors.ink2, modifier = Modifier.weight(1f),
                    textAlign = androidx.compose.ui.text.style.TextAlign.Center)
                TextButton(enabled = pager.currentPage < list.size - 1, onClick = { scope.launch { pager.animateScrollToPage(pager.currentPage + 1) } }) {
                    Text("Next", color = Theme.colors.cobalt)
                }
            }
        }
    }
}
