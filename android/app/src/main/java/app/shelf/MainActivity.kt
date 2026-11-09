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
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import app.shelf.ui.AppNav
import app.shelf.ui.start.ServerScreen
import app.shelf.ui.start.SignInScreen
import app.shelf.ui.start.StartViewModel
import app.shelf.ui.theme.Shelf
import app.shelf.ui.theme.ShelfTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        val container = (application as ShelfApp).container
        setContent {
            ShelfTheme {
                val start: StartViewModel = viewModel(factory = viewModelFactory {
                    initializer { StartViewModel(container.store) { container.api!! } }
                })
                val state by start.state.collectAsStateWithLifecycle()
                LaunchedEffect(Unit) { start.start() }
                Box(Modifier.fillMaxSize().background(Shelf.colors.tray)) {
                    when (state.step) {
                        StartViewModel.Step.Checking -> Unit
                        StartViewModel.Step.Server -> ServerScreen(state, start::submitServer)
                        StartViewModel.Step.SignIn -> SignInScreen(state, start::signIn, start::changeServer)
                        StartViewModel.Step.Done -> AppNav(container, signedOut = start::signedOut)
                    }
                }
            }
        }
    }
}
