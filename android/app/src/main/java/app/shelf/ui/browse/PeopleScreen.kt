package app.shelf.ui.browse

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.shelf.R
import app.shelf.data.Activity
import app.shelf.data.Person
import app.shelf.data.ShelfApi
import app.shelf.ui.SignedOutHandler
import app.shelf.ui.common.ArtistAvatar
import app.shelf.ui.common.LoadContent
import app.shelf.ui.common.rememberLoad
import app.shelf.ui.covers.CaseCover
import app.shelf.ui.covers.albumColor
import app.shelf.ui.covers.fallbackColor
import app.shelf.ui.theme.Shelf
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope

private class PeopleData(val activity: List<Activity>, val people: List<Person>)

/** People on this server: what they're playing (friend activity), and a Blend with each of them. */
@Composable
fun PeopleScreen(api: ShelfApi, onBlend: (Int) -> Unit, onAlbum: (Int) -> Unit, onBack: () -> Unit, signedOut: SignedOutHandler) {
    val (state, retry) = rememberLoad("people") {
        coroutineScope { val a = async { api.activity() }; val p = async { api.people() }; PeopleData(a.await(), p.await()) }
    }
    LoadContent(state, retry, signedOut) { d ->
        LazyColumn(Modifier.fillMaxSize()) {
            item {
                Row(Modifier.statusBarsPadding().padding(4.dp), verticalAlignment = Alignment.CenterVertically) {
                    IconButton(onClick = onBack) { Icon(painterResource(R.drawable.ic_back), "Back", tint = Shelf.colors.ink) }
                    Text("People", style = MaterialTheme.typography.headlineSmall, color = Shelf.colors.ink)
                }
            }
            if (d.people.isEmpty()) item {
                Text("You're the only one on this server. Add people in the admin dashboard, and you can see what they play and make Blends.",
                    style = MaterialTheme.typography.bodyMedium, color = Shelf.colors.ink2, modifier = Modifier.padding(20.dp))
            }
            if (d.activity.isNotEmpty()) item { Heading("Friend activity") }
            items(d.activity, key = { "a${it.user.id}" }) { a ->
                val t = a.now?.track ?: a.last?.track ?: return@items
                Row(Modifier.fillMaxWidth().clickable { onAlbum(t.albumId) }.padding(horizontal = 16.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    CaseCover(api.coverUrl(t.albumId, t.cover, 160), t.album, fallbackColor(t.album), Modifier.size(52.dp))
                    Spacer(Modifier.width(14.dp))
                    Column(Modifier.weight(1f)) {
                        Text(a.user.username, style = MaterialTheme.typography.titleMedium, color = Shelf.colors.ink)
                        Text("${t.title}, ${t.artist}", style = MaterialTheme.typography.bodyMedium, color = Shelf.colors.ink2, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        val where = when {
                            a.now?.playing == true -> "Playing now" + (a.now.device?.let { " on $it" } ?: "")
                            a.now != null -> "Paused" + (a.now.device?.let { " on $it" } ?: "")
                            else -> "Last played " + ago(a.last!!.at)
                        }
                        Text(where, style = MaterialTheme.typography.bodySmall, color = if (a.now?.playing == true) Shelf.colors.cobalt else Shelf.colors.ink2)
                    }
                }
            }
            if (d.people.isNotEmpty()) item { Heading("Blend") }
            items(d.people, key = { "p${it.id}" }) { p ->
                Row(Modifier.fillMaxWidth().clickable(enabled = p.canBlend) { onBlend(p.id) }.padding(horizontal = 16.dp, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    ArtistAvatar(null, p.username, albumColor(null, p.username), Modifier.size(52.dp))
                    Spacer(Modifier.width(14.dp))
                    Column(Modifier.weight(1f)) {
                        Text(p.username, style = MaterialTheme.typography.titleMedium, color = Shelf.colors.ink)
                        Text(if (p.canBlend) "A playlist of both your tastes" else "Keeps their listening to themselves",
                            style = MaterialTheme.typography.bodySmall, color = Shelf.colors.ink2)
                    }
                }
            }
            item { Spacer(Modifier.size(24.dp)) }
        }
    }
}

@Composable
private fun Heading(text: String) = Text(text, style = MaterialTheme.typography.titleLarge, color = Shelf.colors.ink,
    modifier = Modifier.padding(start = 16.dp, top = 18.dp, bottom = 6.dp))

/** "5 minutes ago", "3 hours ago", "2 days ago". */
private fun ago(at: Double, now: Double = System.currentTimeMillis() / 1000.0): String {
    val s = (now - at).coerceAtLeast(0.0)
    return when {
        s < 90 -> "just now"
        s < 3600 -> "${(s / 60).toInt()} minutes ago"
        s < 7200 -> "an hour ago"
        s < 86400 -> "${(s / 3600).toInt()} hours ago"
        s < 172800 -> "yesterday"
        else -> "${(s / 86400).toInt()} days ago"
    }
}
