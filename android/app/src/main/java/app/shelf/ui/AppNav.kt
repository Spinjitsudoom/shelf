package app.shelf.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import androidx.activity.compose.BackHandler
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import kotlinx.coroutines.launch
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.background
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.shelf.AppContainer
import app.shelf.playback.PlayerConnection
import app.shelf.playback.PlayerUi
import app.shelf.ui.player.MiniPlayer
import app.shelf.ui.player.NowPlayingScreen
import app.shelf.data.LibrarySource
import app.shelf.ui.browse.AlbumScreen
import app.shelf.ui.browse.ArtistScreen
import app.shelf.ui.browse.FavouritesScreen
import app.shelf.ui.browse.HomeScreen
import app.shelf.ui.browse.LibraryScreen
import app.shelf.ui.browse.MixScreen
import app.shelf.ui.browse.OnPlay
import app.shelf.ui.browse.PlaylistScreen
import app.shelf.R
import app.shelf.ui.theme.Shelf

/** A screen that finds the sign-in no longer works calls this (back to sign-in, same server). */
fun interface SignedOutHandler { fun signedOut() }

object Routes {
    const val HOME = "home"
    const val LIBRARY = "library"
    const val FAVOURITES = "favourites"
    const val SETTINGS = "settings"
    const val SEARCH = "search"
    const val ADMIN = "web/admin"
    fun album(id: Int) = "album/$id"
    fun artist(name: String) = "artist/${android.net.Uri.encode(name)}"
    fun playlist(id: Int) = "playlist/$id"
    fun mix(key: String) = "mix/${android.net.Uri.encode(key)}"
    fun trackRadio(id: Int) = "radio/track/$id"
    fun artistRadio(name: String) = "radio/artist/${android.net.Uri.encode(name)}"
}

private data class Tab(val route: String, val label: String, val icon: Int)
private val TABS = listOf(Tab(Routes.HOME, "Home", R.drawable.ic_home), Tab(Routes.SEARCH, "Search", R.drawable.ic_search), Tab(Routes.LIBRARY, "Library", R.drawable.ic_library))

/** The signed-in app: screens, the mini player above the bottom bar, and the bar itself. */
@Composable
fun AppNav(container: AppContainer, signedOut: SignedOutHandler, player: PlayerConnection? = null,
           onChangeServer: () -> Unit = {}, onSignOut: () -> Unit = {}) {
    val source: LibrarySource = remember(container.api) { container.api?.let { app.shelf.downloads.OfflineSource(it, container.downloads.index) } } ?: return
    val nav = rememberNavController()
    val playing by (player?.state ?: kotlinx.coroutines.flow.MutableStateFlow(PlayerUi())).collectAsStateWithLifecycle()
    var nowPlaying by rememberSaveable { mutableStateOf(false) }
    val onPlay: OnPlay = { tracks, index, ctx -> player?.play(tracks, index, ctx) }
    val cover = { t: app.shelf.data.Track -> source.coverUrl(t.albumId, t.cover, 160) }
    BackHandler(enabled = nowPlaying) { nowPlaying = false }
    val snackbar = remember { androidx.compose.material3.SnackbarHostState() }
    val scope = androidx.compose.runtime.rememberCoroutineScope()
    val say: (String) -> Unit = { msg -> scope.launch { snackbar.currentSnackbarData?.dismiss(); snackbar.showSnackbar(msg) } }
    val likes by container.likes.ids.collectAsStateWithLifecycle()
    val connectUi by container.connect.ui.collectAsStateWithLifecycle()
    val playingOn = if (connectUi.remote) connectUi.activeDevice?.name?.ifBlank { "Web browser" } else null
    var devicesOpen by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { container.likes.refresh() }
    var menu by remember { mutableStateOf<Pair<app.shelf.data.Track, (() -> Unit)?>?>(null) }
    var adding by remember { mutableStateOf<app.shelf.data.Track?>(null) }
    var playlists by remember { mutableStateOf<List<app.shelf.data.PlaylistSummary>?>(null) }
    val api = container.api
    val failed = "Couldn’t save that. Check the connection and try again."
    LaunchedEffect(adding) { if (adding != null) playlists = try { source.playlists() } catch (e: app.shelf.data.ShelfError) { emptyList() } }
    val actions = remember { app.shelf.ui.common.SongActions(open = { t, remove -> menu = t to remove }) }
    CompositionLocalProvider(app.shelf.ui.common.LocalSongActions provides actions, app.shelf.downloads.LocalDownloads provides container.downloads) {
    Box(Modifier.fillMaxSize()) {
    val entry by nav.currentBackStackEntryAsState()
    val current = entry?.destination?.route
    Scaffold(
        containerColor = Shelf.colors.tray,
        snackbarHost = { androidx.compose.material3.SnackbarHost(snackbar) },
        bottomBar = {
            Column {
                if (player != null && playing.current != null) {
                    MiniPlayer(playing, cover, player::toggle, player::next, player::previous, { nowPlaying = true }, device = playingOn)
                }
                NavigationBar(containerColor = Shelf.colors.sleeve) {
                    TABS.forEach { tab ->
                        NavigationBarItem(
                            selected = current == tab.route,
                            onClick = { nav.navigateTab(tab.route) },
                            icon = { Icon(painterResource(tab.icon), contentDescription = null) },
                            label = { Text(tab.label, style = MaterialTheme.typography.labelMedium) },
                            colors = NavigationBarItemDefaults.colors(selectedIconColor = Shelf.colors.cobalt, selectedTextColor = Shelf.colors.cobalt,
                                indicatorColor = Shelf.colors.cobalt.copy(alpha = .14f), unselectedIconColor = Shelf.colors.ink2, unselectedTextColor = Shelf.colors.ink2),
                        )
                    }
                }
            }
        },
    ) { inner ->
        NavHost(nav, startDestination = Routes.HOME, modifier = Modifier.padding(inner)) {
            val openAlbum = { id: Int -> nav.navigate(Routes.album(id)) }
            val openArtist = { name: String -> nav.navigate(Routes.artist(name)) }
            val back: () -> Unit = { nav.popBackStack() }
            composable(Routes.HOME) {
                HomeScreen(source, container.store.username, openAlbum, { nav.navigate(Routes.mix(it)) }, openAlbum, signedOut,
                    onSettings = { nav.navigate(Routes.SETTINGS) })
            }
            composable(Routes.SEARCH) { app.shelf.ui.search.SearchScreen(container.api!!, onPlay, openAlbum, openArtist) }
            composable(Routes.LIBRARY) {
                LibraryScreen(source, { nav.navigate(Routes.FAVOURITES) }, { nav.navigate(Routes.playlist(it)) }, openAlbum, openArtist, signedOut,
                    onNewPlaylist = api?.let { a -> { name: String -> scope.launch {
                        try { val p = a.createPlaylist(name); nav.navigate(Routes.playlist(p.id)) } catch (e: app.shelf.data.ShelfError) { say(failed) }
                    } } })
            }
            composable(Routes.FAVOURITES) { FavouritesScreen(source, onPlay, back, signedOut) }
            composable("album/{id}", listOf(navArgument("id") { type = NavType.IntType })) {
                AlbumScreen(it.arguments!!.getInt("id"), source, onPlay, openArtist, back, signedOut)
            }
            composable("artist/{name}") {
                val name = it.arguments!!.getString("name")!!
                ArtistScreen(name, source, onPlay, openAlbum, back, signedOut, onRadio = api?.let { { nav.navigate(Routes.artistRadio(name)) } })
            }
            composable("playlist/{id}", listOf(navArgument("id") { type = NavType.IntType })) {
                PlaylistScreen(it.arguments!!.getInt("id"), source, onPlay, back, signedOut, api = api, say = say)
            }
            if (api != null) {
                composable("radio/track/{id}", listOf(navArgument("id") { type = NavType.IntType })) {
                    app.shelf.ui.browse.RadioScreen(it.arguments!!.getInt("id"), null, api, onPlay, back, signedOut)
                }
                composable("radio/artist/{name}") {
                    app.shelf.ui.browse.RadioScreen(null, it.arguments!!.getString("name")!!, api, onPlay, back, signedOut)
                }
            }
            composable("mix/{key}") { MixScreen(it.arguments!!.getString("key")!!, source, onPlay, back, signedOut) }
            composable(Routes.SETTINGS) {
                app.shelf.ui.settings.SettingsScreen(container, app.shelf.BuildConfig.VERSION_NAME, onChangeServer, onSignOut, back,
                    onAdmin = { nav.navigate(Routes.ADMIN) })
            }
            composable(Routes.ADMIN) {
                app.shelf.ui.web.WebPageScreen(container.store.server ?: "", container.store.token, "#/admin", back)
            }
        }
    }
    AnimatedVisibility(nowPlaying && player != null && playing.current != null,
        enter = slideInVertically { it }, exit = slideOutVertically { it }) {
        Box(Modifier.fillMaxSize().background(Shelf.colors.tray)) {
            NowPlayingScreen(playing, source, player!!,
                liked = playing.current?.id in likes,
                onLike = { playing.current?.let { t -> container.likes.toggle(t.id, say) } },
                onArtist = { nowPlaying = false; nav.navigate(Routes.artist(it)) },
                onContext = { nowPlaying = false; nav.navigate(it) },
                onClose = { nowPlaying = false },
                lyrics = api?.let { a -> { id: Int -> a.lyrics(id) } },
                device = playingOn, onDevices = { devicesOpen = true })
        }
    }
    menu?.let { (t, remove) ->
        val liked = t.id in likes
        val items = buildList {
            add(app.shelf.ui.common.MenuItem("Play next", R.drawable.ic_next_up) { player?.playNext(listOf(t)); say("“${t.title}” plays next") })
            add(app.shelf.ui.common.MenuItem("Add to queue", R.drawable.ic_queue) { player?.addToQueue(listOf(t)); say("Added “${t.title}” to the queue") })
            add(app.shelf.ui.common.MenuItem(if (liked) "Remove from Favourites" else "Add to Favourites", R.drawable.ic_heart) {
                container.likes.toggle(t.id, say); say(if (liked) "Removed from Favourites" else "Added to Favourites") })
            if (api != null) {
                add(app.shelf.ui.common.MenuItem("Add to playlist…", R.drawable.ic_playlist) { playlists = null; adding = t })
                add(app.shelf.ui.common.MenuItem("Song radio", R.drawable.ic_radio) { nowPlaying = false; nav.navigate(Routes.trackRadio(t.id)) })
            }
            if (remove != null) add(app.shelf.ui.common.MenuItem("Remove from this playlist", R.drawable.ic_trash) { remove() })
            add(app.shelf.ui.common.MenuItem("Go to album", R.drawable.ic_album_go) { nowPlaying = false; nav.navigate(Routes.album(t.albumId)) })
            t.artists.ifEmpty { listOf(t.artist) }.forEach { a ->
                add(app.shelf.ui.common.MenuItem("Go to $a", R.drawable.ic_artists) { nowPlaying = false; nav.navigate(Routes.artist(a)) })
            }
        }
        app.shelf.ui.common.SongMenu(t, source.coverUrl(t.albumId, t.cover, 160), items) { menu = null }
    }
    if (devicesOpen) app.shelf.ui.player.DevicesSheet(connectUi, onPick = { id ->
        val u = connectUi
        val playingNowhere = u.activeId == null || u.devices.none { it.id == u.activeId }
        if (!u.connected) say("Can’t reach the server to see your other devices")
        else if (id != u.activeId && !(id == u.selfId && playingNowhere)) {
            // This phone's queue goes along when the server has none (nothing's playing anywhere else).
            val snap = if (!u.remote && playing.queue.isNotEmpty()) app.shelf.connect.Snapshot(playing.queue, playing.index.coerceAtLeast(0),
                playing.positionMs / 1000.0, playing.playing, playing.shuffle,
                when (playing.repeat) { androidx.media3.common.Player.REPEAT_MODE_ALL -> "all"; androidx.media3.common.Player.REPEAT_MODE_ONE -> "one"; else -> "off" },
                playing.context?.let { app.shelf.connect.WebContext(it.label, app.shelf.connect.webHref(it.route)) }) else null
            container.connect.send(app.shelf.connect.transferMessage(id, snap))
        }
    }, onDismiss = { devicesOpen = false })
    adding?.let { t ->
        if (api != null) app.shelf.ui.common.AddToPlaylistSheet(playlists, { p -> p.covers.mapNotNull { source.coverUrl(it.albumId, it.cover, 160) } },
            onPick = { p -> scope.launch { try { api.addToPlaylist(p.id, listOf(t.id)); say("Added to ${p.name}") } catch (e: app.shelf.data.ShelfError) { say(failed) } } },
            onNew = { name -> scope.launch { try { api.createPlaylist(name, listOf(t.id)); say("Added to $name") } catch (e: app.shelf.data.ShelfError) { say(failed) } } },
            onDismiss = { adding = null })
    }
    }
    }
}

/** Switching tabs keeps one copy of each tab, with its scroll position. */
private fun NavHostController.navigateTab(route: String) = navigate(route) {
    popUpTo(graph.findStartDestination().id) { saveState = true }
    launchSingleTop = true
    restoreState = true
}

