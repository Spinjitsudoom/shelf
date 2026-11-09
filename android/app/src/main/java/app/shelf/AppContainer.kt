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
    val settings = app.shelf.settings.SettingsStore(context.getSharedPreferences("settings", Context.MODE_PRIVATE))

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

    /** Favourites, for every heart in the app. */
    val likes = app.shelf.data.LikesStore({ api }, kotlinx.coroutines.CoroutineScope(kotlinx.coroutines.SupervisorJob() + kotlinx.coroutines.Dispatchers.Main))

    private var cachedFor: String? = null
    private var cached: ShelfApi? = null

    /** The API of any server address (checking one that was just typed, before it's saved). */
    fun apiFor(server: String): ShelfApi = ShelfApi("$server/".toHttpUrl(), { store.token }, okHttp)

    /** The API for the chosen server (null before one is chosen). */
    val api: ShelfApi?
        get() {
            val s = store.server ?: return null
            if (s != cachedFor) { cached = apiFor(s); cachedFor = s }
            return cached
        }
}
