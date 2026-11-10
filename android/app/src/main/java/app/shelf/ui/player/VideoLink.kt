package app.shelf.ui.player

import android.content.Intent
import android.net.Uri

/** Ways to open a YouTube video at [atSeconds]: the YouTube app first, then the browser. */
fun youtubeIntents(videoId: String, atSeconds: Int): List<Intent> = listOf(
    Intent(Intent.ACTION_VIEW, Uri.parse("vnd.youtube:$videoId?t=$atSeconds")),
    Intent(Intent.ACTION_VIEW, Uri.parse("https://www.youtube.com/watch?v=$videoId&t=${atSeconds}s")),
).onEach { it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK) }
