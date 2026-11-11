package app.shelf.ui.web

import android.annotation.SuppressLint
import android.webkit.CookieManager
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.viewinterop.AndroidView
import app.shelf.ui.theme.Shelf

/**
 * One of the web app's pages inside the app (the admin dashboard: users, adding music, CD ripping,
 * server updates), signed in with the app's sign-in. Back goes back within the page first.
 */
@SuppressLint("SetJavaScriptEnabled")
@Composable
fun WebPageScreen(server: String, token: String?, path: String, onClose: () -> Unit) {
    var web by remember { mutableStateOf<WebView?>(null) }
    BackHandler { web?.takeIf { it.canGoBack() }?.goBack() ?: onClose() }
    AndroidView(
        modifier = Modifier.fillMaxSize().background(Shelf.colors.tray).statusBarsPadding(),
        factory = { ctx ->
            if (token != null) {
                CookieManager.getInstance().setCookie(server, "shelf_session=$token; path=/")
                CookieManager.getInstance().flush()
            }
            // Like Shelf Lite: the page can be inspected from a computer (chrome://inspect) when something breaks.
            WebView.setWebContentsDebuggingEnabled(true)
            WebView(ctx).apply {
                // Without this the WebView is "wrap content": it gives the page a 0 px tall window, and
                // the web app (sized to the window's height) collapses to nothing.
                layoutParams = android.view.ViewGroup.LayoutParams(android.view.ViewGroup.LayoutParams.MATCH_PARENT,
                    android.view.ViewGroup.LayoutParams.MATCH_PARENT)
                settings.javaScriptEnabled = true
                settings.domStorageEnabled = true
                setBackgroundColor(android.graphics.Color.TRANSPARENT)
                // Links inside Shelf stay here; anything else opens in the browser.
                webViewClient = object : WebViewClient() {
                    override fun shouldOverrideUrlLoading(view: WebView, request: android.webkit.WebResourceRequest): Boolean {
                        if (request.url.toString().startsWith(server)) return false
                        runCatching { view.context.startActivity(android.content.Intent(android.content.Intent.ACTION_VIEW, request.url)) }
                        return true
                    }
                }
                webChromeClient = object : android.webkit.WebChromeClient() {
                    override fun onConsoleMessage(m: android.webkit.ConsoleMessage): Boolean {
                        if (m.messageLevel() == android.webkit.ConsoleMessage.MessageLevel.ERROR)
                            android.util.Log.w("ShelfWeb", "${m.message()} (${m.sourceId()}:${m.lineNumber()})")
                        return true
                    }
                }
                loadUrl("$server/$path")
                web = this
            }
        },
        onRelease = { it.destroy() },
    )
}
