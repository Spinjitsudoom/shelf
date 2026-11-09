package app.shelf;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.SystemClock;
import android.content.pm.PackageManager;
import org.json.JSONObject;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;

/**
 * Shelf for Android: the Shelf web app, opened at the server you pick.
 *
 * The first screen (assets/start.html) asks for the server's address and checks a Shelf
 * server answers there. After that the app opens straight onto that server, where you
 * sign in. Settings > Change server (or the server box on the sign-in screen) comes back here.
 */
public class MainActivity extends Activity {
    private static final String START = "file:///android_asset/start.html";

    private WebView web;
    private FrameLayout root;
    private View fullscreen;
    private WebChromeClient.CustomViewCallback fullscreenDone;
    private SharedPreferences prefs;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        prefs = getSharedPreferences("shelf", MODE_PRIVATE);
        root = new FrameLayout(this);
        root.setBackgroundColor(Color.parseColor("#1a1d24"));
        setContentView(root);
        makeWebView();

        // The notification and lock screen buttons, headphones and car displays control the web player.
        // Lets a computer with USB debugging inspect the page (chrome://inspect).
        WebView.setWebContentsDebuggingEnabled(true);
        PlaybackService.commands = new PlaybackService.Commands() {
            public void command(String name, double arg) {
                if (web != null) web.evaluateJavascript("window.shelfNative && shelfNative.command("
                    + JSONObject.quote(name) + "," + arg + ")", null);
            }
        };
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission("android.permission.POST_NOTIFICATIONS") != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[] {"android.permission.POST_NOTIFICATIONS"}, 1);
        }

        if (state != null) {
            web.restoreState(state);
        } else {
            openServer();
        }
    }

    private void openServer() {
        String server = server();
        if (server == null) web.loadUrl(START);
        else web.loadUrl(server + "/");
    }

    private void makeWebView() {
        web = new WebView(this);
        root.addView(web, 0, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false); // playback moved here from another device starts by itself
        s.setAllowFileAccess(true); // the start page
        s.setUserAgentString(s.getUserAgentString() + " ShelfAndroid/" + appVersion());
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, true); // YouTube's player
        web.setBackgroundColor(Color.parseColor("#1a1d24"));
        web.addJavascriptInterface(new Bridge(), "ShelfAndroid");
        web.setWebViewClient(new Client());
        web.setWebChromeClient(new Chrome());
        // Keep the page running at full priority with the screen off, so songs change on time.
        if (Build.VERSION.SDK_INT >= 26) web.setRendererPriorityPolicy(WebView.RENDERER_PRIORITY_IMPORTANT, false);
    }

    private String server() {
        return prefs.getString("server", null);
    }

    private void showStart(String error) {
        String url = START;
        if (error != null) url += "#error=" + Uri.encode(error);
        web.loadUrl(url);
    }

    private boolean isServer(Uri uri) {
        String server = server();
        if (server == null) return false;
        Uri s = Uri.parse(server);
        return s.getScheme().equals(uri.getScheme()) && s.getAuthority().equals(uri.getAuthority());
    }

    /** True for pages of the chosen server (and the start page), which stay in the app. */
    private boolean isOurs(Uri uri) {
        if (uri.toString().startsWith(START)) return true;
        String server = server();
        if (server == null) return false;
        Uri s = Uri.parse(server);
        return s.getScheme().equals(uri.getScheme()) && s.getAuthority().equals(uri.getAuthority());
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        web.saveState(out);
    }

    @Override
    protected void onPause() {
        super.onPause();
        // The web view is left running so music keeps playing with the screen off.
        CookieManager.getInstance().flush();
    }

    /** The volume buttons, while this phone controls another device: that device's volume. */
    @Override
    public boolean dispatchKeyEvent(KeyEvent e) {
        int code = e.getKeyCode();
        if (code == KeyEvent.KEYCODE_VOLUME_UP || code == KeyEvent.KEYCODE_VOLUME_DOWN) {
            PlaybackService.State s = PlaybackService.current();
            if (s != null && !s.device.isEmpty()) {
                if (e.getAction() == KeyEvent.ACTION_DOWN
                    && !PlaybackService.adjustRemoteVolume(code == KeyEvent.KEYCODE_VOLUME_UP ? 1 : -1)) {
                    return super.dispatchKeyEvent(e);
                }
                return true;
            }
        }
        return super.dispatchKeyEvent(e);
    }

    @Override
    public void onBackPressed() {
        if (fullscreen != null) {
            fullscreenDone.onCustomViewHidden();
        } else if (web.canGoBack()) {
            web.goBack();
        } else {
            moveTaskToBack(true); // like Home, so music keeps playing
        }
    }

    @Override
    protected void onDestroy() {
        PlaybackService.commands = null;
        PlaybackService.update(this, null); // the music stops with the app
        web.destroy();
        super.onDestroy();
    }

    /** What the pages can ask of the phone, as window.ShelfAndroid. */
    private class Bridge {
        /** Save the server address and open it. Only the start page may do this. */
        @JavascriptInterface
        public void setServer(final String url) {
            runOnUiThread(new Runnable() {
                public void run() {
                    String current = web.getUrl();
                    if (current == null || !current.startsWith(START)) return;
                    Uri u = Uri.parse(url);
                    if (!"http".equals(u.getScheme()) && !"https".equals(u.getScheme())) return;
                    if (u.getHost() == null) return;
                    String clean = url.replaceAll("/+$", "");
                    prefs.edit().putString("server", clean).apply();
                    web.clearHistory();
                    web.loadUrl(clean + "/");
                }
            });
        }

        @JavascriptInterface
        public String getServer() {
            String s = server();
            return s == null ? "" : s;
        }

        /** Back to the start page, to pick another server. */
        @JavascriptInterface
        public void changeServer() {
            runOnUiThread(new Runnable() {
                public void run() { showStart(null); }
            });
        }

        @JavascriptInterface
        public void signedIn(String username) { /* for the media notification, later */ }

        @JavascriptInterface
        public String version() { return appVersion(); }

        /** What's playing (JSON from the web player), for the notification and lock screen. */
        @JavascriptInterface
        public void mediaState(String json) {
            PlaybackService.State st = null;
            try {
                if (json != null && !"null".equals(json)) {
                    JSONObject o = new JSONObject(json);
                    st = new PlaybackService.State();
                    st.title = o.optString("title");
                    st.artist = o.optString("artist");
                    st.album = o.optString("album");
                    st.art = o.optString("art");
                    st.device = o.optString("device");
                    st.duration = o.optDouble("duration", 0);
                    st.position = o.optDouble("position", 0);
                    st.playing = o.optBoolean("playing");
                    st.volume = o.optDouble("volume", 1);
                    st.hasPrev = o.optBoolean("hasPrev", true);
                    st.hasNext = o.optBoolean("hasNext", true);
                    st.at = SystemClock.elapsedRealtime();
                    // Only our server's covers, or a downloaded one passed inline.
                    if (!st.art.isEmpty() && !st.art.startsWith("data:image/") && !isOurs(Uri.parse(st.art))) st.art = "";
                }
            } catch (Exception e) {
                return;
            }
            final PlaybackService.State fin = st;
            runOnUiThread(new Runnable() {
                public void run() { PlaybackService.update(MainActivity.this, fin); }
            });
        }
    }

    private class Client extends WebViewClient {
        /**
         * The web app's own files (not the music or the API): fetched as usual, and a copy is
         * kept, so with no connection the app still opens and plays what's downloaded.
         */
        @Override
        public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest req) {
            Uri uri = req.getUrl();
            if (!"GET".equals(req.getMethod()) || !isServer(uri)) return null;
            String path = uri.getPath() == null ? "/" : uri.getPath();
            if (path.startsWith("/api/")) return null;
            return ShellCache.fetch(MainActivity.this, uri.toString(), path, req.getRequestHeaders());
        }

        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
            if (!req.isForMainFrame()) return false; // the YouTube player and such
            return leave(req.getUrl());
        }

        @Override
        @SuppressWarnings("deprecation")
        public boolean shouldOverrideUrlLoading(WebView view, String url) {
            return leave(Uri.parse(url));
        }

        /** Links to anywhere else (YouTube, Wikipedia) open in their own app or the browser. */
        private boolean leave(Uri uri) {
            if (isOurs(uri)) return false;
            try {
                startActivity(new Intent(Intent.ACTION_VIEW, uri));
            } catch (Exception ignored) { }
            return true;
        }

        @Override
        public void onReceivedError(WebView view, WebResourceRequest req, WebResourceError err) {
            if (Build.VERSION.SDK_INT >= 23 && req.isForMainFrame()) failed(req.getUrl().toString());
        }

        @Override
        @SuppressWarnings("deprecation")
        public void onReceivedError(WebView view, int code, String description, String url) {
            if (Build.VERSION.SDK_INT < 23) failed(url);
        }

        /** The page's renderer was closed (low memory): start it again rather than crash. */
        @Override
        public boolean onRenderProcessGone(WebView view, android.webkit.RenderProcessGoneDetail detail) {
            if (view != web) return true;
            root.removeView(web);
            web.destroy();
            makeWebView();
            openServer();
            return true;
        }

        private void failed(String url) {
            if (url.startsWith(START)) return;
            String s = server();
            showStart("Couldn’t reach " + (s == null ? url : s.replaceFirst("^https?://", ""))
                + ". Check the server is running and that this phone is on the same network.");
        }
    }

    /** Full screen for music videos. */
    private class Chrome extends WebChromeClient {
        @Override
        public void onShowCustomView(View view, CustomViewCallback done) {
            if (fullscreen != null) { done.onCustomViewHidden(); return; }
            fullscreen = view;
            fullscreenDone = done;
            root.addView(view, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
            getWindow().addFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN);
            view.setSystemUiVisibility(View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY);
        }

        @Override
        public void onHideCustomView() {
            if (fullscreen == null) return;
            root.removeView(fullscreen);
            fullscreen = null;
            getWindow().clearFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN);
            fullscreenDone.onCustomViewHidden();
        }
    }

    /** The app's version (set by the build from the release tag). */
    String appVersion() {
        try {
            return getPackageManager().getPackageInfo(getPackageName(), 0).versionName;
        } catch (Exception e) {
            return "?";
        }
    }
}
