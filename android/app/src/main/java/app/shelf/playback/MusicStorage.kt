package app.shelf.playback

import android.content.Context
import androidx.annotation.OptIn
import androidx.media3.common.util.UnstableApi
import androidx.media3.database.StandaloneDatabaseProvider
import androidx.media3.datasource.cache.LeastRecentlyUsedCacheEvictor
import androidx.media3.datasource.cache.NoOpCacheEvictor
import androidx.media3.datasource.cache.SimpleCache
import java.io.File

/**
 * Where music is kept on the phone. Two stores: recently played songs (500 MB, the oldest go
 * first, in the cache folder Android may clear), and downloads (never evicted, in the app's
 * own files). The player reads downloads first, then the recent cache, then the server.
 */
@OptIn(UnstableApi::class)
object MusicStorage {
    private var database: StandaloneDatabaseProvider? = null
    private var recent: SimpleCache? = null
    private var downloads: SimpleCache? = null

    @Synchronized fun database(context: Context) = database ?: StandaloneDatabaseProvider(context.applicationContext).also { database = it }

    @Synchronized fun recent(context: Context): SimpleCache = recent ?: SimpleCache(
        File(context.cacheDir, "music"), LeastRecentlyUsedCacheEvictor(500L * 1024 * 1024), database(context),
    ).also { recent = it }

    @Synchronized fun downloads(context: Context): SimpleCache = downloads ?: SimpleCache(
        File(context.filesDir, "downloads"), NoOpCacheEvictor(), database(context),
    ).also { downloads = it }
}
