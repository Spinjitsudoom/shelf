package app.shelf.ui.browse

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.shelf.R
import app.shelf.data.PartyStatus
import app.shelf.data.ShelfApi
import app.shelf.data.ShelfError
import app.shelf.data.Track
import app.shelf.ui.common.TrackRow
import app.shelf.ui.common.fmtTime
import app.shelf.ui.covers.CaseCover
import app.shelf.ui.covers.albumColor
import app.shelf.ui.covers.fallbackColor
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import app.shelf.ui.theme.Shelf as Theme

/** The vote line under Vote to skip. */
fun votesText(votes: Int, needed: Int) = "$votes of $needed ${if (needed == 1) "vote" else "votes"} to skip"

/**
 * Someone's party: what's playing (with Vote to skip), songs to add, and up next. Joins on
 * opening, and keeps itself up to date every few seconds.
 */
@Composable
fun PartyScreen(api: ShelfApi, host: Int, onBack: () -> Unit, say: (String) -> Unit,
                party: kotlinx.coroutines.flow.MutableStateFlow<app.shelf.playback.PartyJoin?> = kotlinx.coroutines.flow.MutableStateFlow(null)) {
    val joined by party.collectAsState()
    var status by remember { mutableStateOf<PartyStatus?>(null) }
    var gone by remember { mutableStateOf<String?>(null) }
    var query by remember { mutableStateOf("") }
    var found by remember { mutableStateOf<List<Track>>(emptyList()) }
    var added by remember { mutableStateOf(setOf<Int>()) }
    val scope = rememberCoroutineScope()
    suspend fun refresh() {
        try {
            val s = api.party(host)
            if (!s.joined) api.joinParty(host)
            // A guest follows the host's playing (Play here, on unless they turned it off at this party).
            if (!s.isHost && party.value?.host != host) party.value = app.shelf.playback.PartyJoin(host)
            status = s
        } catch (e: ShelfError.Server) { gone = e.message } catch (_: ShelfError) { /* offline for a moment: keep what's shown */ }
    }
    LaunchedEffect(host) { while (true) { refresh(); delay(4000) } }
    LaunchedEffect(query) {
        if (query.isBlank()) { found = emptyList(); return@LaunchedEffect }
        delay(250)
        found = runCatching { api.search(query.trim()).tracks.take(12) }.getOrDefault(found)
    }

    LazyColumn(Modifier.fillMaxSize()) {
        val s = status
        item {
            Row(Modifier.statusBarsPadding().padding(4.dp), verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = onBack) { Icon(painterResource(R.drawable.ic_back), "Back", tint = Theme.colors.ink) }
                Text(when { s == null -> "Party"; s.isHost -> "Your party"; else -> "${s.host.username}’s party" },
                    style = MaterialTheme.typography.headlineSmall, color = Theme.colors.ink, modifier = Modifier.weight(1f))
                if (s != null) TextButton(onClick = {
                    scope.launch {
                        runCatching { if (s.isHost) api.endParty() else api.leaveParty(host) }
                        if (party.value?.host == host) party.value = null
                        say(if (s.isHost) "Party’s over" else "You left the party"); onBack()
                    }
                }) { Text(if (s.isHost) "End party" else "Leave", color = Theme.colors.ink) }
            }
            if (s != null) Text(s.members.joinToString(", "), style = MaterialTheme.typography.bodyMedium, color = Theme.colors.ink2,
                modifier = Modifier.padding(horizontal = 16.dp))
            if (s != null && !s.isHost) Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Play here", style = MaterialTheme.typography.titleMedium, color = Theme.colors.ink)
                    Text("Hear it on this phone, in step with ${s.host.username}. Turn it off when you’re in the same room.",
                        style = MaterialTheme.typography.bodySmall, color = Theme.colors.ink2)
                }
                androidx.compose.material3.Switch(checked = joined?.host == host && joined?.playHere == true,
                    onCheckedChange = { on -> party.value = app.shelf.playback.PartyJoin(host, playHere = on) })
            }
            gone?.let { Text(it, style = MaterialTheme.typography.bodyLarge, color = Theme.colors.ink, modifier = Modifier.padding(16.dp)) }
        }
        if (s == null) return@LazyColumn
        item {
            val now = s.nowPlaying
            if (now == null) {
                Text(if (s.isHost) "Nothing’s playing yet. Play something on any of your devices, and it plays here."
                     else "When ${s.host.username} plays something, it shows here.",
                    style = MaterialTheme.typography.bodyLarge, color = Theme.colors.ink2, modifier = Modifier.padding(16.dp))
            } else Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                CaseCover(api.coverUrl(now.albumId, now.cover, 320), now.album, fallbackColor(now.album), Modifier.size(120.dp))
                Spacer(Modifier.width(16.dp))
                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(if (s.playing) "Playing now" else "Paused", style = MaterialTheme.typography.labelLarge, color = Theme.colors.ink2)
                    Text(now.title, style = MaterialTheme.typography.titleLarge, color = Theme.colors.ink, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    Text(now.artist, style = MaterialTheme.typography.bodyMedium, color = Theme.colors.ink2, maxLines = 1)
                    Button(enabled = !s.youVoted, onClick = {
                        scope.launch {
                            runCatching { api.partySkip(host) }.onSuccess { v -> say(if (v.skipped) "Skipped" else votesText(v.votes, v.needed)) }
                            refresh()
                        }
                    }, colors = ButtonDefaults.buttonColors(containerColor = Theme.colors.cobalt, contentColor = Theme.colors.cobaltInk)) {
                        Text(if (s.youVoted) "You voted to skip" else "Vote to skip")
                    }
                    Text(votesText(s.votes, s.needed), style = MaterialTheme.typography.bodySmall, color = Theme.colors.ink2)
                }
            }
        }
        item {
            Text("Add songs", style = MaterialTheme.typography.titleLarge, color = Theme.colors.ink, modifier = Modifier.padding(16.dp, 8.dp))
            OutlinedTextField(query, { query = it }, label = { Text("Search for a song") }, singleLine = true,
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp))
        }
        items(found, key = { "f${it.id}" }) { t ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    TrackRow(null, t.title, t.artist, fmtTime(t.duration), {}, coverUrl = api.coverUrl(t.albumId, t.cover, 160),
                        coverColor = albumColor(null, t.album))
                }
                TextButton(enabled = t.id !in added, onClick = {
                    scope.launch {
                        try { api.partyAdd(host, listOf(t.id)); added = added + t.id; say("Added: it plays after the songs added before it"); refresh() }
                        catch (e: ShelfError.Server) { say(e.message ?: "Couldn’t add that") } catch (_: ShelfError) { say("Couldn’t add that. Check the connection.") }
                    }
                }) { Text(if (t.id in added) "Added" else "Add", color = Theme.colors.cobalt) }
            }
        }
        if (s.upNext.isNotEmpty()) item {
            Text("Up next", style = MaterialTheme.typography.titleLarge, color = Theme.colors.ink, modifier = Modifier.padding(16.dp, 12.dp, 16.dp, 4.dp))
        }
        itemsIndexed(s.upNext, key = { i, _ -> "n$i" }) { _, t ->
            TrackRow(null, t.title, t.artist, fmtTime(t.duration), {}, coverUrl = api.coverUrl(t.albumId, t.cover, 160), coverColor = albumColor(null, t.album))
        }
        item { Spacer(Modifier.height(24.dp)) }
    }
}
