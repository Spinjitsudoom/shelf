package app.shelf

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import app.shelf.playback.PlayerConnection
import app.shelf.ui.AppNav
import app.shelf.ui.start.ServerScreen
import app.shelf.ui.start.SignInScreen
import app.shelf.ui.start.StartViewModel
import app.shelf.ui.theme.Shelf
import app.shelf.ui.theme.ShelfTheme

class MainActivity : ComponentActivity() {
    private var player: PlayerConnection? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        val container = (application as ShelfApp).container
        app.shelf.update.Updater.schedule(this) // look for new versions in the background (released app only)
        val player = PlayerConnection(this) { container.api }.also { this.player = it }
        setContent {
            val settings by container.settings.settings.collectAsStateWithLifecycle()
            val dark = when (settings.theme) { "light" -> false; "system" -> androidx.compose.foundation.isSystemInDarkTheme(); else -> true }
            // The status and navigation bar icons follow Shelf's theme, not the phone's.
            androidx.compose.runtime.LaunchedEffect(dark) {
                val clear = android.graphics.Color.TRANSPARENT
                enableEdgeToEdge(
                    statusBarStyle = if (dark) androidx.activity.SystemBarStyle.dark(clear) else androidx.activity.SystemBarStyle.light(clear, clear),
                    navigationBarStyle = if (dark) androidx.activity.SystemBarStyle.dark(clear) else androidx.activity.SystemBarStyle.light(clear, clear),
                )
            }
            androidx.compose.runtime.CompositionLocalProvider(app.shelf.settings.LocalSettings provides settings) { ShelfTheme(dark = dark) {
                val start: StartViewModel = viewModel(factory = viewModelFactory {
                    initializer { StartViewModel(container.store, container::apiFor) }
                })
                val state by start.state.collectAsStateWithLifecycle()
                LaunchedEffect(Unit) { start.start() }
                Box(Modifier.fillMaxSize().background(Shelf.colors.tray)) {
                    when (state.step) {
                        StartViewModel.Step.Checking -> Unit
                        StartViewModel.Step.Server -> ServerScreen(state, start::submitServer)
                        StartViewModel.Step.SignIn -> SignInScreen(state, start::signIn, start::changeServer)
                        StartViewModel.Step.Done -> {
                            var onboard by androidx.compose.runtime.saveable.rememberSaveable { androidx.compose.runtime.mutableStateOf(app.shelf.ui.start.needsOnboarding(this@MainActivity)) }
                            if (onboard) app.shelf.ui.start.Onboarding { onboard = false }
                            else AppNav(container, signedOut = start::signedOut, player = player,
                                onChangeServer = start::changeServer, onSignOut = start::signOut)
                        }
                    }
                }
            } }
        }
    }

    override fun onDestroy() {
        player?.release() // the music itself lives on in PlaybackService
        super.onDestroy()
    }
}
