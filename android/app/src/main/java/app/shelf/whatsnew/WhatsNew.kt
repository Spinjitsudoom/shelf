package app.shelf.whatsnew

import android.content.Context
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import app.shelf.ui.theme.Shelf
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json

/**
 * "What's new": after an update, once, what's new and what's fixed. The notes are the web app's
 * (src/shelf/web/whatsnew.json, copied into the app when it's built), one entry per release.
 */
@Serializable data class Item(val title: String, val text: String, val admin: Boolean = false)
@Serializable data class Release(val version: String, val date: String? = null, val new: List<Item> = emptyList(), val fixed: List<String> = emptyList()) {
    /** Without the admin-only items, for everyone else. */
    fun forPerson(admin: Boolean) = if (admin) this else copy(new = new.filterNot { it.admin })
}

private val json = Json { ignoreUnknownKeys = true }

fun parseNotes(text: String): List<Release> = runCatching { json.decodeFromString(ListSerializer(Release.serializer()), text) }.getOrDefault(emptyList())

private fun parts(v: String) = v.split('.').map { it.takeWhile(Char::isDigit).toIntOrNull() ?: 0 }

/** Whether version [a] is later than [b] ("0.10.0" is later than "0.9.9"). */
fun newer(a: String, b: String): Boolean {
    val x = parts(a); val y = parts(b)
    for (i in 0 until maxOf(x.size, y.size)) {
        val p = x.getOrElse(i) { 0 }; val q = y.getOrElse(i) { 0 }
        if (p != q) return p > q
    }
    return false
}

/**
 * The releases to show now: those since [seen] up to [current] (at most three). With nothing
 * seen yet, this version's, but only if the app was [updated] (a new install shows nothing).
 */
fun toShow(all: List<Release>, seen: String?, current: String, updated: Boolean): List<Release> = when {
    seen == null -> if (updated) all.filter { it.version == current } else emptyList()
    !newer(current, seen) -> emptyList()
    else -> all.filter { newer(it.version, seen) && !newer(it.version, current) }.take(3)
}

/** Remembers the last version whose notes were shown on this phone. */
class WhatsNewStore(private val context: Context) {
    private val prefs = context.getSharedPreferences("whatsnew", Context.MODE_PRIVATE)

    fun all(): List<Release> = runCatching { context.assets.open("whatsnew.json").use { parseNotes(it.readBytes().decodeToString()) } }.getOrDefault(emptyList())

    /** What to show after an update (once: it's marked as seen). */
    fun pending(): List<Release> {
        @Suppress("DEPRECATION")
        val info = context.packageManager.getPackageInfo(context.packageName, 0)
        val current = info.versionName ?: return emptyList()
        val list = toShow(all(), prefs.getString("seen", null), current, updated = info.lastUpdateTime > info.firstInstallTime)
        prefs.edit().putString("seen", current).apply()
        return list
    }
}

@Composable
fun WhatsNewDialog(releases: List<Release>, admin: Boolean, onDismiss: () -> Unit, heading: String? = null) {
    val shown = releases.map { it.forPerson(admin) }
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = Shelf.colors.sleeve,
        icon = { Box(Modifier.size(48.dp).background(Shelf.colors.cobalt, CircleShape), contentAlignment = Alignment.Center) {
            Box(Modifier.size(12.dp).background(Shelf.colors.sleeve, CircleShape)) } },
        title = { Text(heading ?: if (shown.size > 1) "Shelf has been updated" else "What’s new in Shelf ${shown.first().version}", color = Shelf.colors.ink) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                shown.forEach { r ->
                    if (shown.size > 1) Text("Shelf ${r.version}", style = MaterialTheme.typography.titleMedium, color = Shelf.colors.ink,
                        modifier = Modifier.padding(top = 10.dp))
                    if (r.new.isNotEmpty()) Label("New")
                    r.new.forEach { i ->
                        Column(Modifier.padding(vertical = 3.dp)) {
                            Text(i.title, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.SemiBold, color = Shelf.colors.ink)
                            Text(i.text, style = MaterialTheme.typography.bodyMedium, color = Shelf.colors.ink2)
                        }
                    }
                    if (r.fixed.isNotEmpty()) Label("Fixed")
                    r.fixed.forEach { f ->
                        Row(verticalAlignment = Alignment.Top) {
                            Box(Modifier.padding(top = 8.dp, end = 10.dp).size(6.dp).background(Shelf.colors.cobalt, CircleShape))
                            Text(f, style = MaterialTheme.typography.bodyMedium, color = Shelf.colors.ink)
                        }
                    }
                }
            }
        },
        confirmButton = { Button(onClick = onDismiss) { Text("Got it") } },
    )
}

@Composable
private fun Label(text: String) =
    Text(text, style = MaterialTheme.typography.labelLarge, color = Shelf.colors.ink2, modifier = Modifier.padding(top = 8.dp))
