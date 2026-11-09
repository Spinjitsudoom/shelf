package app.shelf.playback

import android.content.Context
import androidx.annotation.OptIn
import androidx.media3.common.util.BitmapLoader
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DataSourceBitmapLoader
import androidx.media3.datasource.okhttp.OkHttpDataSource
import androidx.media3.session.CacheBitmapLoader
import okhttp3.OkHttpClient

/** How the notification, lock screen, Bluetooth and car displays get album covers: through the
 * signed-in client (the server only gives covers to a signed-in request), remembering the last one. */
@OptIn(UnstableApi::class)
fun artworkLoader(context: Context, okHttp: OkHttpClient): BitmapLoader =
    CacheBitmapLoader(DataSourceBitmapLoader.Builder(context).setDataSourceFactory(OkHttpDataSource.Factory(okHttp)).build())
