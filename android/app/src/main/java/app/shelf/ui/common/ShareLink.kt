package app.shelf.ui.common

import android.content.Context
import android.content.Intent
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedIconButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.compositionLocalOf
import androidx.compose.ui.res.painterResource
import app.shelf.R
import app.shelf.data.ShelfApi
import app.shelf.data.ShelfError
import app.shelf.ui.theme.Shelf
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch

/** The message sent with a share link: what it is, the link, and how long it works. */
fun shareText(kind: String, title: String, by: String?, url: String, days: Int?): String {
    val what = when (kind) {
        "album" -> "the album “$title”"
        "playlist" -> "my playlist “$title”"
        else -> "“$title”"
    }
    val who = if (kind != "playlist" && !by.isNullOrBlank()) " by $by" else ""
    val lasts = when (days) {
        null -> ""
        1 -> " (the link works for a day)"
        7 -> " (the link works for a week)"
        else -> " (the link works for $days days)"
    }
    return "Listen to $what$who: $url$lasts"
}

/**
 * Share links (when the server's admin has turned them on): makes a link to a song, album or
 * playlist that anyone can listen to without an account, and hands it to Android's share sheet.
 * Links made here work for a week; the web app's Settings lists them, to stop one sooner.
 */
class ShareLinks(val enabled: Boolean, private val api: ShelfApi?, private val context: Context,
                 private val scope: CoroutineScope, private val say: (String) -> Unit) {
    fun share(kind: String, id: Int, title: String, by: String?) {
        val a = api ?: return
        scope.launch {
            try {
                val link = a.makeShare(kind, id, DAYS)
                val send = Intent(Intent.ACTION_SEND).setType("text/plain")
                    .putExtra(Intent.EXTRA_SUBJECT, title)
                    .putExtra(Intent.EXTRA_TEXT, shareText(kind, title, by, a.linkFor(link.path), DAYS))
                context.startActivity(Intent.createChooser(send, "Share link").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            } catch (e: ShelfError.Server) {
                say(e.message ?: "Couldn’t make a link")
            } catch (e: ShelfError) {
                say("Couldn’t make a link. Check the connection and try again.")
            }
        }
    }

    companion object { const val DAYS = 7 }
}

val LocalShareLinks = compositionLocalOf<ShareLinks?> { null }

/** The link button on an album's or playlist's page (only when share links are on). */
@Composable
fun ShareLinkButton(kind: String, id: Int, title: String, by: String?) {
    val links = LocalShareLinks.current ?: return
    if (!links.enabled) return
    OutlinedIconButton(onClick = { links.share(kind, id, title, by) }) {
        Icon(painterResource(R.drawable.ic_link), "Share link", tint = Shelf.colors.ink)
    }
}
