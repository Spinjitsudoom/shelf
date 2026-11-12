package app.shelf.ui.common

import android.net.Uri
import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.shelf.R
import app.shelf.data.ImportResult
import app.shelf.ui.covers.CaseCover
import app.shelf.ui.covers.albumColor
import app.shelf.ui.theme.Shelf
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/*
 * Importing playlists from elsewhere (see src/shelf/imports.py): a Spotify or YouTube link (typed,
 * or shared to Shelf from those apps), a playlist file, a CSV export or a list of songs. The server
 * finds the songs in the library; this shows what it found, then makes the playlists.
 */

private val PLAYLIST_LINK = Regex(
    """https?://(?:open\.spotify\.com/(?:intl-[\w-]+/)?(?:playlist|album)/[A-Za-z0-9]+|(?:www\.|m\.|music\.)?youtube\.com/(?:playlist|watch)\?[^\s]*\blist=[\w-]+)[^\s]*""")

/** The Spotify or YouTube playlist link in text shared from another app, or null. */
fun sharedPlaylistLink(text: String): String? = PLAYLIST_LINK.find(text)?.value

/** The import form: what to look up, what the server found, and which playlists to make. */
class ImportForm(initial: String = "") {
    var text by mutableStateOf(initial)
        private set
    var file by mutableStateOf<Pair<String, String>?>(null) // name, contents
        private set
    var result by mutableStateOf<ImportResult?>(null)
        private set
    var picked by mutableStateOf(emptySet<Int>())
        private set
    var error by mutableStateOf<String?>(null)
    var working by mutableStateOf(false)
        private set
    private val names = mutableStateMapOf<Int, String>()

    fun type(value: String) { text = value; if (value.isNotBlank()) file = null; error = null }
    fun chooseFile(name: String, contents: String) { file = name to contents; text = ""; error = null }
    fun back() { result = null; error = null }
    fun name(i: Int): String = names[i] ?: result?.playlists?.getOrNull(i)?.name.orEmpty()
    fun rename(i: Int, value: String) { names[i] = value }
    fun toggle(i: Int) { picked = if (i in picked) picked - i else picked + i }
    fun trackIds(i: Int): List<Int> = result?.playlists?.getOrNull(i)?.songs.orEmpty().mapNotNull { it.track?.id }.distinct()

    /** Look the songs up. True when found (the results show); otherwise [error] says why. */
    suspend fun find(onFind: suspend (text: String, filename: String) -> ImportResult): Boolean {
        val (what, filename) = if (text.isNotBlank()) text to "" else file?.let { it.second to it.first } ?: ("" to "")
        if (what.isBlank()) { error = "Paste a link or a list of songs, or choose a file."; return false }
        working = true
        try {
            val found = onFind(what, filename)
            result = found
            names.clear()
            picked = found.playlists.indices.filter { trackIds(it).isNotEmpty() }.toSet()
            error = if (picked.isEmpty()) "None of these songs are in your library." else null
            return true
        } catch (e: Exception) {
            error = e.message ?: "Shelf couldn’t import that."
            return false
        } finally {
            working = false
        }
    }

    /** Make the picked playlists. The new playlists' ids (empty, with [error] set, if none). */
    suspend fun make(onMake: suspend (name: String, description: String, trackIds: List<Int>) -> Int): List<Int> {
        val found = result ?: return emptyList()
        val chosen = picked.sorted().filter { trackIds(it).isNotEmpty() }
        if (chosen.isEmpty()) { error = "Pick at least one playlist."; return emptyList() }
        working = true
        try {
            return chosen.map { i ->
                val p = found.playlists[i]
                val missing = p.songs.count { it.track == null }
                val description = "Imported${if (found.linked) " from a link" else ""}." +
                    if (missing > 0) " ${plural(missing, "song")} ${if (missing == 1) "wasn’t" else "weren’t"} in the library." else ""
                onMake(name(i).trim().ifEmpty { p.name }, description, trackIds(i))
            }
        } catch (e: Exception) {
            error = e.message ?: "Shelf couldn’t make the playlist."
            return emptyList()
        } finally {
            working = false
        }
    }
}

private const val MAX_FILE = 8 * 1024 * 1024

private fun readFile(context: android.content.Context, uri: Uri): Pair<String, String>? {
    val r = context.contentResolver
    val name = r.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
        if (c.moveToFirst()) c.getString(0) else null
    } ?: uri.lastPathSegment ?: "playlist"
    val bytes = r.openInputStream(uri)?.use { input ->
        val out = java.io.ByteArrayOutputStream()
        val buf = ByteArray(64 * 1024)
        while (out.size() <= MAX_FILE) { val n = input.read(buf); if (n < 0) break; out.write(buf, 0, n) }
        out.toByteArray()
    } ?: return null
    if (bytes.size > MAX_FILE) return null
    return name to bytes.toString(Charsets.UTF_8)
}

/**
 * The Import a playlist dialog. [onFind] asks the server (throwing with the reason on failure);
 * [onMake] makes one playlist and returns its id; [onDone] gets the new playlists' ids and names.
 */
@Composable
fun ImportPlaylistDialog(
    initial: String,
    coverUrl: (Int, String?) -> String?,
    onFind: suspend (String, String) -> ImportResult,
    onMake: suspend (String, String, List<Int>) -> Int,
    onDone: (List<Pair<Int, String>>) -> Unit,
    onDismiss: () -> Unit,
) {
    val form = remember { ImportForm(initial) }
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    val pick = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        if (uri != null) scope.launch {
            val got = withContext(Dispatchers.IO) { runCatching { readFile(context, uri) }.getOrNull() }
            if (got != null) form.chooseFile(got.first, got.second) else form.error = "Shelf couldn’t read that file."
        }
    }
    val found = form.result
    AlertDialog(
        onDismissRequest = onDismiss, containerColor = Shelf.colors.sleeve,
        title = { Text("Import a playlist", color = Shelf.colors.ink) },
        text = {
            if (found == null) Column {
                Text("From Spotify or YouTube, another music player, or a list of songs. Shelf finds them in your library.",
                    color = Shelf.colors.ink2, style = MaterialTheme.typography.bodyMedium)
                Spacer(Modifier.height(10.dp))
                OutlinedTextField(form.text, form::type, label = { Text("Link or list of songs") }, minLines = 3, maxLines = 6,
                    placeholder = { Text("A Spotify or YouTube playlist link, or one song per line") },
                    modifier = Modifier.fillMaxWidth(), isError = form.error != null)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    TextButton(onClick = { pick.launch("*/*") }) {
                        Icon(painterResource(R.drawable.ic_download), null, tint = Shelf.colors.cobalt, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(6.dp))
                        Text("Choose a file", color = Shelf.colors.cobalt)
                    }
                    form.file?.let { Text(it.first, color = Shelf.colors.ink2, style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis) }
                }
                Text(form.error ?: "Links show up to 100 songs. Files: M3U, PLS, XSPF, CSV exports and Spotify’s data download.",
                    color = if (form.error != null) MaterialTheme.colorScheme.error else Shelf.colors.ink2, style = MaterialTheme.typography.bodySmall)
            } else Column {
                val many = found.playlists.size > 1
                LazyColumn(Modifier.heightIn(max = 460.dp)) {
                    found.playlists.forEachIndexed { i, p ->
                        item(key = "head$i") {
                            Column(Modifier.padding(top = if (i > 0) 14.dp else 0.dp)) {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    if (many) Checkbox(i in form.picked, { form.toggle(i) }, enabled = form.trackIds(i).isNotEmpty(),
                                        colors = CheckboxDefaults.colors(checkedColor = Shelf.colors.cobalt))
                                    OutlinedTextField(form.name(i), { form.rename(i, it) }, label = { Text("Name") }, singleLine = true,
                                        modifier = Modifier.weight(1f))
                                }
                                Spacer(Modifier.height(6.dp))
                                val missing = p.songs.count { it.track == null }
                                Text("${p.songs.size - missing} of ${plural(p.songs.size, "song")} ${if (p.songs.size - missing == 1) "is" else "are"} in your library.",
                                    color = Shelf.colors.ink, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodyMedium)
                            }
                        }
                        if (!many) itemsIndexed(p.songs, key = { j, _ -> "s$i-$j" }) { _, s -> ImportedRow(s, coverUrl) }
                    }
                }
                form.error?.let {
                    Spacer(Modifier.height(8.dp))
                    Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
                }
            }
        },
        confirmButton = {
            if (found == null) TextButton(enabled = !form.working, onClick = { scope.launch { form.find(onFind) } }) {
                Text(if (form.working) "Finding…" else "Find the songs", color = Shelf.colors.cobalt)
            } else TextButton(enabled = !form.working && form.picked.isNotEmpty(), onClick = {
                scope.launch {
                    val ids = form.make(onMake)
                    if (ids.isNotEmpty()) onDone(ids.zip(form.picked.sorted().filter { form.trackIds(it).isNotEmpty() }.map { form.name(it) }))
                }
            }) { Text(if (form.working) "Making…" else if (found.playlists.size > 1) "Import" else "Make the playlist", color = Shelf.colors.cobalt) }
        },
        dismissButton = {
            TextButton(onClick = { if (found == null) onDismiss() else form.back() }) {
                Text(if (found == null) "Cancel" else "Back", color = Shelf.colors.ink2)
            }
        },
    )
}

@Composable
private fun ImportedRow(s: app.shelf.data.ImportedSong, coverUrl: (Int, String?) -> String?) {
    val t = s.track
    Row(Modifier.fillMaxWidth().padding(vertical = 5.dp), verticalAlignment = Alignment.CenterVertically) {
        if (t != null) CaseCover(coverUrl(t.albumId, t.cover), t.album, albumColor(null, t.album), Modifier.size(40.dp))
        else Box(Modifier.size(40.dp).border(1.5.dp, Shelf.colors.ink2.copy(alpha = .35f), RoundedCornerShape(4.dp)))
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(t?.title ?: s.want, color = if (t != null) Shelf.colors.ink else Shelf.colors.ink2, maxLines = 1, overflow = TextOverflow.Ellipsis,
                style = MaterialTheme.typography.bodyLarge)
            Text(t?.artist ?: "Not in your library", color = Shelf.colors.ink2, maxLines = 1, overflow = TextOverflow.Ellipsis,
                style = MaterialTheme.typography.bodySmall)
        }
    }
}
