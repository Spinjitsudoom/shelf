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
import app.shelf.AppContainer
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
    fun album(id: Int) = "album/$id"
    fun artist(name: String) = "artist/${android.net.Uri.encode(name)}"
    fun playlist(id: Int) = "playlist/$id"
    fun mix(key: String) = "mix/${android.net.Uri.encode(key)}"
}

private data class Tab(val route: String, val label: String, val icon: Int)
private val TABS = listOf(Tab(Routes.HOME, "Home", R.drawable.ic_home), Tab(Routes.LIBRARY, "Library", R.drawable.ic_library))

/** The signed-in app: screens, the mini player above the bottom bar, and the bar itself. */
@Composable
fun AppNav(container: AppContainer, signedOut: SignedOutHandler, miniPlayer: @Composable () -> Unit = {},
           onPlay: OnPlay = { _, _, _ -> }) {
    val source: LibrarySource = container.api ?: return
    val nav = rememberNavController()
    val entry by nav.currentBackStackEntryAsState()
    val current = entry?.destination?.route
    Scaffold(
        containerColor = Shelf.colors.tray,
        bottomBar = {
            Column {
                miniPlayer()
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
                HomeScreen(source, container.store.username, openAlbum, { nav.navigate(Routes.mix(it)) }, openAlbum, signedOut)
            }
            composable(Routes.LIBRARY) {
                LibraryScreen(source, { nav.navigate(Routes.FAVOURITES) }, { nav.navigate(Routes.playlist(it)) }, openAlbum, openArtist, signedOut)
            }
            composable(Routes.FAVOURITES) { FavouritesScreen(source, onPlay, back, signedOut) }
            composable("album/{id}", listOf(navArgument("id") { type = NavType.IntType })) {
                AlbumScreen(it.arguments!!.getInt("id"), source, onPlay, openArtist, back, signedOut)
            }
            composable("artist/{name}") { ArtistScreen(it.arguments!!.getString("name")!!, source, onPlay, openAlbum, back, signedOut) }
            composable("playlist/{id}", listOf(navArgument("id") { type = NavType.IntType })) {
                PlaylistScreen(it.arguments!!.getInt("id"), source, onPlay, back, signedOut)
            }
            composable("mix/{key}") { MixScreen(it.arguments!!.getString("key")!!, source, onPlay, back, signedOut) }
        }
    }
}

/** Switching tabs keeps one copy of each tab, with its scroll position. */
private fun NavHostController.navigateTab(route: String) = navigate(route) {
    popUpTo(graph.findStartDestination().id) { saveState = true }
    launchSingleTop = true
    restoreState = true
}

