package app.shelf.ui.common

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedIconButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.shelf.R
import app.shelf.downloads.Downloadable
import app.shelf.downloads.LocalDownloads
import app.shelf.ui.theme.Shelf

/** Download an album, playlist or Favourites: an arrow, a ring while it downloads, a tick when it's on the phone. */
@Composable
fun DownloadButton(item: Downloadable) {
    val downloads = LocalDownloads.current ?: return
    val items by downloads.items.collectAsStateWithLifecycle()
    val progress by downloads.progress.collectAsStateWithLifecycle()
    var removing by remember { mutableStateOf(false) }
    val saved = items.any { it.key == item.key }
    val done = saved && (progress[item.key] ?: 0f) >= 1f
    // Bring the phone's copy up to date (a changed playlist) and retry songs that failed.
    LaunchedEffect(item, saved) { if (saved) downloads.sync(item) }
    OutlinedIconButton(onClick = { if (saved) removing = true else downloads.download(item) }) {
        when {
            done -> Icon(painterResource(R.drawable.ic_downloaded), "Downloaded. Remove the download", tint = Shelf.colors.cobalt)
            saved -> Box(contentAlignment = Alignment.Center) {
                CircularProgressIndicator(progress = { progress[item.key] ?: 0f }, modifier = Modifier.size(30.dp), color = Shelf.colors.cobalt,
                    trackColor = Shelf.colors.ink.copy(alpha = .15f), strokeWidth = 2.5.dp)
                Icon(painterResource(R.drawable.ic_download), "Downloading. Stop and remove", tint = Shelf.colors.ink2, modifier = Modifier.size(16.dp))
            }
            else -> Icon(painterResource(R.drawable.ic_download), "Download", tint = Shelf.colors.ink)
        }
    }
    if (removing) ConfirmDialog("Remove the download?", "“${item.name}” won’t play without a connection any more. It stays on your shelf.", "Remove",
        { downloads.remove(item.kind, item.id) }, { removing = false })
}
