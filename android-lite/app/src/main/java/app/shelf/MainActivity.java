package app.shelf;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.MutableContextWrapper;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.os.SystemClock;
import android.content.pm.PackageManager;
import android.provider.Settings;
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
 *
 * The music plays in the web view, and the web view outlives this screen: swipe Shelf away
 * while music plays and it carries on in the background (PlaybackService keeps the app
 * running), and opening Shelf again picks the same web view back up, exactly where it was.
 * Left paused with no screen for ten minutes, it's let go (see PlaybackService).
 */
public class MainActivity extends Activity {
    private static final String START = "file:///android_asset/start.html";
    private static final Handler MAIN = new Handler(Looper.getMainLooper());

    /** The one web view, kept here (not in the screen) so the music survives the screen. */
    private static WebView web;
    /** The screen showing it, if any. */
    private static MainActivity shown;
    private static Context app;

    private FrameLayout root;
    private View fullscreen;
    private WebChromeClient.CustomViewCallback fullscreenDone;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        app = getApplicationContext();
        Updater.schedule(this);  // look for new versions of the app in the background
        Updater.checkSoon(this);
        root = new FrameLayout(this);
        root.setBackgroundColor(Color.parseColor("#1a1d24"));
        setContentView(root);
        shown = this;

        // Lets a computer with USB debugging inspect the page (chrome://inspect).
        WebView.setWebContentsDebuggingEnabled(true);
        // The notification and lock screen buttons, headphones and car displays control the web player.
        PlaybackService.commands = new PlaybackService.Commands() {
            public void command(String name, double arg) {
                if (web != null) web.evaluateJavascript("window.shelfNative && shelfNative.command("
                    + JSONObject.quote(name) + "," + arg + ")", null);
            }
        };
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission("android.permission.POST_NOTIFICATIONS") != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[] {"android.permission.POST_NOTIFICATIONS"}, 1);
        }

        if (web != null) {
            // Still playing from before the screen closed: take it back, as it is.
            ((MutableContextWrapper) web.getContext()).setBaseContext(this);
            ViewGroup parent = (ViewGroup) web.getParent();
            if (parent != null) parent.removeView(web);
            root.addView(web, 0, fill());
            web.setWebChromeClient(new Chrome());
            return;
        }
        makeWebView(this);
        root.addView(web, 0, fill());
        if (state != null) web.restoreState(state);
        else openServer();
    }

    private static FrameLayout.LayoutParams fill() {
        return new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT);
    }

    private static SharedPreferences prefs() {
        return app.getSharedPreferences("shelf", MODE_PRIVATE);
    }

    private static String server() {
        return prefs().getString("server", null);
    }

    private static void openServer() {
        final String server = server();
        if (server == null) { web.loadUrl(START); return; }
        web.loadUrl(server + "/");
        // On plain http from the internet, and the server has a secure address: move there, signed in.
        if (!SecureMove.worthAsking(server)) return;
        new Thread(new Runnable() {
            public void run() {
                final String to = SecureMove.target(server);
                if (to == null) return;
                MAIN.post(new Runnable() {
                    public void run() {
                        if (web == null || !server.equals(server())) return;
                        SecureMove.carrySignIn(server, to);
                        prefs().edit().putString("server", to).apply();
                        web.clearHistory();
                        web.loadUrl(to + "/");
                        android.widget.Toast.makeText(app, "Shelf now connects securely, at " + to.replace("https://", ""),
                            android.widget.Toast.LENGTH_LONG).show();
                    }
                });
            }
        }, "secure-move").start();
    }

    /** The web view, on a context that can move from screen to screen. */
    private static void makeWebView(Context context) {
        web = new WebView(new MutableContextWrapper(context));
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
        web.setWebChromeClient(shown != null ? shown.new Chrome() : new WebChromeClient());
        // Keep the page running at full priority with the screen off, so songs change on time.
        if (Build.VERSION.SDK_INT >= 26) web.setRendererPriorityPolicy(WebView.RENDERER_PRIORITY_IMPORTANT, false);
    }

    private static void showStart(String error) {
        String url = START;
        if (error != null) url += "#error=" + Uri.encode(error);
        web.loadUrl(url);
    }

    private static boolean isServer(Uri uri) {
        String server = server();
        if (server == null) return false;
        Uri s = Uri.parse(server);
        return s.getScheme().equals(uri.getScheme()) && s.getAuthority().equals(uri.getAuthority());
    }

    /** True for pages of the chosen server (and the start page), which stay in the app. */
    private static boolean isOurs(Uri uri) {
        return uri.toString().startsWith(START) || isServer(uri);
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        if (web != null) web.saveState(out);
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
        if (shown == this) shown = null;
        if (web != null && web.getContext() instanceof MutableContextWrapper
            && ((MutableContextWrapper) web.getContext()).getBaseContext() == this) {
            PlaybackService.State s = PlaybackService.current();
            if (s != null && s.keepAwake()) {
                // Swiped away (or closed) mid-song: the music carries on without a screen.
                root.removeView(web);
                ((MutableContextWrapper) web.getContext()).setBaseContext(app);
                web.setWebChromeClient(new WebChromeClient());
            } else {
                release();
            }
        }
        super.onDestroy();
    }

    /** After a restart of the page: once its player is ready, go back to `at` seconds and play. */
    private static void resumeWhenReady(final double at, final int tries) {
        MAIN.postDelayed(new Runnable() {
            public void run() {
                if (web == null) return;
                web.evaluateJavascript("!!(window.shelfNative && window.shelfNative.command)", new android.webkit.ValueCallback<String>() {
                    public void onReceiveValue(String ready) {
                        if (web == null) return;
                        if ("true".equals(ready)) {
                            android.util.Log.i("Shelf", "Page restarted; carrying on at " + at + " s");
                            web.evaluateJavascript("shelfNative.command('seek'," + at + ");shelfNative.command('play',0)", null);
                        } else if (tries < 90) {
                            resumeWhenReady(at, tries + 1);
                        } else if (shown == null) {
                            PlaybackService.update(app, null); // couldn't get back: stop showing music
                        }
                    }
                });
            }
        }, tries == 0 ? 1500 : 500);
    }

    /** Let the web view go: nothing is playing and no screen shows it. */
    static void release() {
        if (web == null) return;
        PlaybackService.commands = null;
        PlaybackService.update(app, null);
        ViewGroup parent = (ViewGroup) web.getParent();
        if (parent != null) parent.removeView(web);
        web.destroy();
        web = null;
    }

    /** Whether the music is running with no screen (PlaybackService lets it go after a while paused). */
    static boolean detached() {
        return web != null && shown == null;
    }

    // ---------- keeping Shelf running in the background ----------

    /** The first time music plays here, offer to take Shelf off the battery saver's list, so
     * Android (and MIUI, which is strict) doesn't stop it in the background. Once. */
    private void offerBackgroundPlay() {
        SharedPreferences p = prefs();
        if (p.getBoolean("askedBackground", false) || isFinishing()) return;
        PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
        boolean xiaomi = Build.MANUFACTURER.toLowerCase().matches(".*(xiaomi|redmi|poco).*");
        if (pm.isIgnoringBatteryOptimizations(getPackageName()) && !xiaomi) return;
        p.edit().putBoolean("askedBackground", true).apply();
        String extra = xiaomi ? "\n\nOn this phone, also turn on Autostart for Shelf, and set its battery saver to "
            + "“No restrictions”, or MIUI may still stop it." : "";
        new AlertDialog.Builder(this)
            .setTitle("Keep the music playing")
            .setMessage("To save battery, Android can stop apps in the background, which would stop your "
                + "music. Let Shelf run without battery restrictions?" + extra)
            .setPositiveButton("Allow", (d, w) -> {
                try {
                    if (!pm.isIgnoringBatteryOptimizations(getPackageName())) {
                        startActivity(new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                            Uri.parse("package:" + getPackageName())));
                    }
                } catch (Exception ignored) { }
                if (xiaomi) MAIN.postDelayed(this::openMiuiAutostart, 600);
            })
            .setNegativeButton("Not now", null)
            .show();
    }

    private void openMiuiAutostart() {
        Intent[] tries = {
            new Intent().setComponent(new ComponentName("com.miui.securitycenter",
                "com.miui.permcenter.autostart.AutoStartManagementActivity")),
            new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:" + getPackageName())),
        };
        for (Intent i : tries) {
            try { startActivity(i); return; } catch (Exception ignored) { }
        }
    }

    /** What the pages can ask of the phone, as window.ShelfAndroid. */
    private static class Bridge {
        /** Save the server address and open it. Only the start page may do this. */
        @JavascriptInterface
        public void setServer(final String url) {
            MAIN.post(new Runnable() {
                public void run() {
                    String current = web == null ? null : web.getUrl();
                    if (current == null || !current.startsWith(START)) return;
                    Uri u = Uri.parse(url);
                    if (!"http".equals(u.getScheme()) && !"https".equals(u.getScheme())) return;
                    if (u.getHost() == null) return;
                    String clean = url.replaceAll("/+$", "");
                    prefs().edit().putString("server", clean).apply();
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
            MAIN.post(new Runnable() {
                public void run() { if (web != null) showStart(null); }
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
            MAIN.post(new Runnable() {
                public void run() {
                    PlaybackService.update(app, fin);
                    if (fin != null && fin.playsHere() && shown != null) shown.offerBackgroundPlay();
                }
            });
        }
    }

    private static class Client extends WebViewClient {
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
            return ShellCache.fetch(app, uri.toString(), path, req.getRequestHeaders());
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
                Context from = shown != null ? shown : app;
                Intent i = new Intent(Intent.ACTION_VIEW, uri);
                if (shown == null) i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                from.startActivity(i);
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

        /**
         * The page's process was closed: by Android when memory runs low, or by MIUI, which kills
         * it when Shelf is swiped away from the recent apps. Start a new one, and if music was
         * playing here, carry on from the same moment once the player is back.
         */
        @Override
        public boolean onRenderProcessGone(WebView view, android.webkit.RenderProcessGoneDetail detail) {
            if (view != web) return true;
            PlaybackService.State s = PlaybackService.current();
            boolean resume = s != null && s.playsHere();
            double at = PlaybackService.positionNow();
            ViewGroup parent = (ViewGroup) web.getParent();
            if (parent != null) parent.removeView(web);
            web.destroy();
            web = null;
            if (shown == null && !resume) {
                PlaybackService.update(app, null); // nothing to carry on with: let it all go
                return true;
            }
            makeWebView(shown != null ? shown : app);
            if (shown != null) shown.root.addView(web, 0, fill());
            openServer();
            if (resume) resumeWhenReady(at, 0);
            return true;
        }

        private void failed(String url) {
            if (url.startsWith(START)) return;
            String s = server();
            showStart("Couldn’t reach " + (s == null ? url : s.replaceFirst("^https?://", ""))
                + ". Check the server is running and that this phone is on the same network.");
        }
    }

    /** Full screen for music videos (only with a screen to show it on). */
    private class Chrome extends WebChromeClient {
        @Override
        public void onShowCustomView(View view, CustomViewCallback done) {
            if (fullscreen != null) { done.onCustomViewHidden(); return; }
            fullscreen = view;
            fullscreenDone = done;
            root.addView(view, fill());
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
    static String appVersion() {
        try {
            return app.getPackageManager().getPackageInfo(app.getPackageName(), 0).versionName;
        } catch (Exception e) {
            return "?";
        }
    }
}
