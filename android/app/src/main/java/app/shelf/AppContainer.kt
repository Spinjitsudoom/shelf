package app.shelf

import android.content.Context
import app.shelf.data.ServerStore
import app.shelf.data.ShelfApi
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import java.util.concurrent.TimeUnit

/** The app's shared pieces: where the server is, the sign-in, and one HTTP client for everything. */
class AppContainer(context: Context) {
    val store = ServerStore(context.getSharedPreferences("shelf", Context.MODE_PRIVATE))

    /** One client for the API, covers (Coil) and music (ExoPlayer). It signs requests to the chosen
     * server, and only that server, with the token. */
    val okHttp: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .addInterceptor { chain ->
            val req = chain.request()
            val server = store.server?.let { runCatching { "$it/".toHttpUrl() }.getOrNull() }
            val token = store.token
            val ours = server != null && req.url.host == server.host && req.url.port == server.port
            chain.proceed(if (ours && token != null && req.header("Authorization") == null)
                req.newBuilder().header("Authorization", "Bearer $token").build() else req)
        }
        .build()

    private var apiFor: String? = null
    private var cached: ShelfApi? = null

    /** The API for the chosen server (null before one is chosen). */
    val api: ShelfApi?
        get() {
            val s = store.server ?: return null
            if (s != apiFor) { cached = ShelfApi("$s/".toHttpUrl(), { store.token }, okHttp); apiFor = s }
            return cached
        }
}
