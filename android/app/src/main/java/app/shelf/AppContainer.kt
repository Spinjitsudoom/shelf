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

    /** For anything that isn't our server (GitHub, for updates): no sign-in attached. */
    val plainHttp: OkHttpClient by lazy { OkHttpClient.Builder().connectTimeout(20, TimeUnit.SECONDS).readTimeout(60, TimeUnit.SECONDS).build() }

    /** The sleep timer: set from Now Playing, run by the player service. */
    val sleep = app.shelf.playback.SleepTimer()
    /** The party this phone is at (as a guest), and whether it plays along here. */
    val party = kotlinx.coroutines.flow.MutableStateFlow<app.shelf.playback.PartyJoin?>(null)

    /** Favourites, for every heart in the app. */
    val likes = app.shelf.data.LikesStore({ api }, kotlinx.coroutines.CoroutineScope(kotlinx.coroutines.SupervisorJob() + kotlinx.coroutines.Dispatchers.Main))

    /** "What's new" after an update. */
    val whatsNew = app.shelf.whatsnew.WhatsNewStore(context.applicationContext)

    /** Albums, playlists and Favourites kept on the phone (created on first use, on the main thread). */
    val downloads by lazy {
        app.shelf.downloads.Downloads(context.applicationContext, okHttp, { api }, { settings.settings.value.downloadQuality })
            .also { if (settings.movedToOriginal) it.refetchOtherQuality() }
    }

    /** Shelf Connect: this phone among the user's devices (started by the player service). */
    val connect by lazy {
        app.shelf.connect.ConnectClient(app.shelf.connect.DeviceIdentity.of(context.applicationContext).apply { chosenName = settings.settings.value.deviceName }, okHttp,
            { store.server?.takeIf { store.token != null } }) // the server refuses devices that aren't signed in
    }

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
