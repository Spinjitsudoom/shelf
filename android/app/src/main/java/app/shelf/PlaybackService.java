package app.shelf;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.media.AudioAttributes;
import android.media.MediaMetadata;
import android.media.VolumeProvider;
import android.media.session.MediaSession;
import android.media.session.PlaybackState;
import android.net.wifi.WifiManager;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;
import android.os.SystemClock;
import android.webkit.CookieManager;

import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;

/**
 * What's playing, outside the app: the media notification (also on the lock screen), and the
 * media session that headphones, Bluetooth and car displays talk to.
 *
 * The music itself plays in the web view. While it plays on this phone, this runs as a
 * foreground service holding wake and Wi-Fi locks, so the phone doesn't sleep or close the app
 * mid-song. When this phone is the remote for another device, the notification shows and
 * controls that device instead, without keeping anything awake.
 */
public class PlaybackService extends Service {
    private static final String CHANNEL = "playback";
    private static final int NOTIFICATION = 1;
    private static final String ACTION_UPDATE = "app.shelf.UPDATE";
    static final String ACTION_COMMAND = "app.shelf.COMMAND";

    /** Where button presses go: the web player (set by MainActivity). */
    public interface Commands { void command(String name, double arg); }

    /** What's playing, as the web player last reported it. */
    public static class State {
        String title = "", artist = "", album = "", art = "", device = "";
        double duration, position;
        double volume = 1; // the other device's volume, 0..1, when playing there
        boolean playing, hasPrev = true, hasNext = true;
        long at; // SystemClock.elapsedRealtime() when `position` was measured

        boolean playsHere() { return playing && device.isEmpty(); }
    }

    static Commands commands;
    private static State state;
    private static PlaybackService running;
    private static Bitmap widgetArt; // the cover, small enough for a home-screen widget

    static State current() { return state; }
    static Bitmap currentArt() { return widgetArt; }

    /** The web player's latest state; null when nothing is loaded (or signed out). */
    static void update(Context context, State s) {
        state = s;
        if (running != null) { running.refresh(); return; }
        if (s == null) return;
        Intent i = new Intent(context, PlaybackService.class).setAction(ACTION_UPDATE);
        // Started as a foreground service even when paused: Android doesn't let an app in the
        // background (screen off) start an ordinary one. It steps out of the foreground at once.
        try {
            if (Build.VERSION.SDK_INT >= 26) {
                i.putExtra("foreground", true);
                context.startForegroundService(i);
            } else {
                context.startService(i);
            }
        } catch (Exception ignored) { /* not allowed right now; the next update tries again */ }
    }

    private final Handler main = new Handler(Looper.getMainLooper());
    private MediaSession session;
    private NotificationManager notifications;
    private PowerManager.WakeLock wake;
    private WifiManager.WifiLock wifi;
    private boolean foreground;
    private boolean mustStartForeground;
    private Bitmap art;
    private String artUrl = "";
    /** While this phone is the remote: its volume buttons set the other device's volume. */
    private VolumeProvider remoteVolume;
    private long volumeSetAt; // when the buttons last moved it (the page's report lags a moment)
    private static final int VOLUME_STEPS = 100, VOLUME_STEP = 5;

    @Override
    public void onCreate() {
        super.onCreate();
        running = this;
        notifications = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel ch = new NotificationChannel(CHANNEL, "Now playing", NotificationManager.IMPORTANCE_LOW);
            ch.setDescription("Controls for the music that's playing");
            ch.setShowBadge(false);
            notifications.createNotificationChannel(ch);
        }
        wake = ((PowerManager) getSystemService(POWER_SERVICE)).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "shelf:playback");
        wake.setReferenceCounted(false);
        wifi = ((WifiManager) getApplicationContext().getSystemService(WIFI_SERVICE))
            .createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "shelf:playback");
        wifi.setReferenceCounted(false);

        session = new MediaSession(this, "Shelf");
        session.setSessionActivity(openApp());
        session.setCallback(new MediaSession.Callback() {
            @Override public void onPlay() { command("play", 0); }
            @Override public void onPause() { command("pause", 0); }
            @Override public void onStop() { command("pause", 0); }
            @Override public void onSkipToNext() { command("next", 0); }
            @Override public void onSkipToPrevious() { command("prev", 0); }
            @Override public void onSeekTo(long ms) { command("seek", ms / 1000.0); }
        });
        if (Build.VERSION.SDK_INT < 26) {
            //noinspection deprecation
            session.setFlags(MediaSession.FLAG_HANDLES_MEDIA_BUTTONS | MediaSession.FLAG_HANDLES_TRANSPORT_CONTROLS);
        }
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && intent.getBooleanExtra("foreground", false)) mustStartForeground = true;
        if (state == null && mustStartForeground && Build.VERSION.SDK_INT >= 26) {
            // Started from the widget after Shelf was closed: nothing to play. Android insists on
            // a notification first; then the widget shows "tap to open" and this stops.
            NotificationChannel ch = new NotificationChannel(CHANNEL, "Now playing", NotificationManager.IMPORTANCE_LOW);
            notifications.createNotificationChannel(ch);
            Notification n = new Notification.Builder(this, CHANNEL).setSmallIcon(R.drawable.ic_stat)
                .setContentTitle("Shelf").setContentText("Open Shelf to play").setContentIntent(openApp()).build();
            try {
                if (Build.VERSION.SDK_INT >= 29) startForeground(NOTIFICATION, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK);
                else startForeground(NOTIFICATION, n);
            } catch (Exception ignored) { }
            mustStartForeground = false;
            NowPlayingWidget.push(this, null, null);
            shutdown();
            return START_NOT_STICKY;
        }
        if (intent != null && ACTION_COMMAND.equals(intent.getAction())) {
            String name = intent.getStringExtra("cmd");
            if ("dismiss".equals(name)) {
                if (state == null || !state.playsHere()) { state = null; }
            } else {
                command(name, 0);
            }
        }
        refresh();
        return START_NOT_STICKY;
    }

    private void command(final String name, final double arg) {
        android.util.Log.i("Shelf", "command " + name + " " + arg + (commands == null ? " (no page)" : ""));
        // Show the change at once; the web player confirms it a moment later.
        if (state != null && ("play".equals(name) || "pause".equals(name) || "toggle".equals(name))) {
            state.position = position(state);
            state.at = SystemClock.elapsedRealtime();
            state.playing = "play".equals(name) || ("toggle".equals(name) && !state.playing);
            refresh();
        }
        final Commands c = commands;
        if (c != null) main.post(new Runnable() { public void run() { c.command(name, arg); } });
    }

    private static double position(State s) {
        double p = s.position + (s.playing ? (SystemClock.elapsedRealtime() - s.at) / 1000.0 : 0);
        return s.duration > 0 ? Math.min(p, s.duration) : p;
    }

    void refresh() {
        State s = state;
        if (s == null) { shutdown(); return; }

        if (!s.art.equals(artUrl)) loadArt(s.art);
        MediaMetadata.Builder meta = new MediaMetadata.Builder()
            .putString(MediaMetadata.METADATA_KEY_TITLE, s.title)
            .putString(MediaMetadata.METADATA_KEY_ARTIST, s.artist)
            .putString(MediaMetadata.METADATA_KEY_ALBUM, s.album)
            .putLong(MediaMetadata.METADATA_KEY_DURATION, (long) (s.duration * 1000));
        if (art != null) meta.putBitmap(MediaMetadata.METADATA_KEY_ALBUM_ART, art);
        session.setMetadata(meta.build());

        long actions = PlaybackState.ACTION_PLAY | PlaybackState.ACTION_PAUSE | PlaybackState.ACTION_PLAY_PAUSE
            | PlaybackState.ACTION_SEEK_TO | PlaybackState.ACTION_STOP | PlaybackState.ACTION_SKIP_TO_PREVIOUS;
        if (s.hasNext) actions |= PlaybackState.ACTION_SKIP_TO_NEXT;
        session.setPlaybackState(new PlaybackState.Builder()
            .setActions(actions)
            .setState(s.playing ? PlaybackState.STATE_PLAYING : PlaybackState.STATE_PAUSED,
                (long) (s.position * 1000), s.playing ? 1f : 0f, s.at)
            .build());
        syncVolume(s);
        session.setActive(true);

        Notification n = notification(s);
        NowPlayingWidget.push(this, s, widgetArt);
        boolean fg = s.playsHere();
        if (fg || mustStartForeground) {
            try {
                if (Build.VERSION.SDK_INT >= 29) startForeground(NOTIFICATION, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK);
                else startForeground(NOTIFICATION, n);
                foreground = true;
            } catch (Exception e) {
                notifications.notify(NOTIFICATION, n); // not allowed right now; still show it
            }
            mustStartForeground = false;
        }
        if (fg) {
            if (!wake.isHeld()) wake.acquire(6 * 60 * 60 * 1000L);
            if (!wifi.isHeld()) wifi.acquire();
        } else {
            if (foreground) {
                // Paused (or playing elsewhere): the notification can now be swiped away.
                if (Build.VERSION.SDK_INT >= 24) stopForeground(STOP_FOREGROUND_DETACH);
                else stopForeground(false);
                foreground = false;
            }
            if (wake.isHeld()) wake.release();
            if (wifi.isHeld()) wifi.release();
            notifications.notify(NOTIFICATION, n);
        }
    }

    /**
     * Playing on another device: the media session says so, with that device's volume, so the
     * phone's volume buttons (and the volume panel) set it. Playing here:
     * the buttons are the phone's own media volume again.
     */
    private void syncVolume(State s) {
        if (!s.device.isEmpty()) {
            int v = (int) Math.round(Math.max(0, Math.min(1, s.volume)) * VOLUME_STEPS);
            if (remoteVolume == null) {
                remoteVolume = new VolumeProvider(VolumeProvider.VOLUME_CONTROL_ABSOLUTE, VOLUME_STEPS, v) {
                    @Override public void onSetVolumeTo(int volume) { setRemoteVolume(volume); }
                    @Override public void onAdjustVolume(int direction) {
                        if (direction != 0) setRemoteVolume(getCurrentVolume() + direction * VOLUME_STEP);
                    }
                };
                session.setPlaybackToRemote(remoteVolume);
            } else if (SystemClock.elapsedRealtime() - volumeSetAt > 1500 && remoteVolume.getCurrentVolume() != v) {
                remoteVolume.setCurrentVolume(v);
            }
        } else if (remoteVolume != null) {
            remoteVolume = null;
            session.setPlaybackToLocal(new AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build());
        }
    }

    private void setRemoteVolume(int volume) {
        if (remoteVolume == null) return;
        int v = Math.max(0, Math.min(VOLUME_STEPS, volume));
        remoteVolume.setCurrentVolume(v);
        volumeSetAt = SystemClock.elapsedRealtime();
        if (state != null) state.volume = v / (double) VOLUME_STEPS;
        command("volume", v / (double) VOLUME_STEPS);
    }

    /**
     * A volume button pressed while the app is open (direction +1 or -1). True when it went to
     * the device this phone is controlling; false when the phone itself is playing.
     */
    static boolean adjustRemoteVolume(int direction) {
        PlaybackService s = running;
        if (s == null || s.remoteVolume == null) return false;
        s.setRemoteVolume(s.remoteVolume.getCurrentVolume() + direction * VOLUME_STEP);
        return true;
    }

    @SuppressWarnings("deprecation")
    private Notification notification(State s) {
        Notification.Builder b = Build.VERSION.SDK_INT >= 26
            ? new Notification.Builder(this, CHANNEL) : new Notification.Builder(this);
        b.setSmallIcon(R.drawable.ic_stat)
            .setContentTitle(s.title)
            .setContentText(s.artist)
            .setLargeIcon(art)
            .setContentIntent(openApp())
            .setDeleteIntent(commandIntent("dismiss"))
            .setVisibility(Notification.VISIBILITY_PUBLIC)
            .setShowWhen(false)
            .setOngoing(s.playsHere())
            .setColor(0xFF2C4FD0)
            .addAction(new Notification.Action(R.drawable.ic_prev, "Previous", commandIntent("prev")))
            .addAction(s.playing
                ? new Notification.Action(R.drawable.ic_pause, "Pause", commandIntent("pause"))
                : new Notification.Action(R.drawable.ic_play, "Play", commandIntent("play")))
            .addAction(new Notification.Action(R.drawable.ic_next, "Next", commandIntent("next")))
            .setStyle(new Notification.MediaStyle()
                .setMediaSession(session.getSessionToken())
                .setShowActionsInCompactView(0, 1, 2));
        if (!s.device.isEmpty()) b.setSubText("Playing on " + s.device);
        return b.build();
    }

    private PendingIntent openApp() {
        Intent i = new Intent(this, MainActivity.class).setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP);
        return PendingIntent.getActivity(this, 0, i, PendingIntent.FLAG_UPDATE_CURRENT | immutable());
    }

    private PendingIntent commandIntent(String name) {
        Intent i = new Intent(this, PlaybackService.class).setAction(ACTION_COMMAND).putExtra("cmd", name);
        return PendingIntent.getService(this, name.hashCode(), i, PendingIntent.FLAG_UPDATE_CURRENT | immutable());
    }

    private static int immutable() {
        return Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_IMMUTABLE : 0;
    }

    /** Cover art comes from the server, with the app's sign-in cookie. */
    private void loadArt(final String url) {
        artUrl = url;
        art = null;
        widgetArt = null;
        if (url.isEmpty()) return;
        new Thread(new Runnable() {
            public void run() {
                Bitmap bmp = null;
                if (url.startsWith("data:")) {
                    try {
                        byte[] raw = android.util.Base64.decode(url.substring(url.indexOf(',') + 1), android.util.Base64.DEFAULT);
                        bmp = BitmapFactory.decodeByteArray(raw, 0, raw.length);
                    } catch (Exception ignored) { }
                } else try {
                    HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
                    c.setConnectTimeout(8000);
                    c.setReadTimeout(15000);
                    String cookie = CookieManager.getInstance().getCookie(url);
                    if (cookie != null) c.setRequestProperty("Cookie", cookie);
                    InputStream in = c.getInputStream();
                    try { bmp = BitmapFactory.decodeStream(in); } finally { in.close(); }
                } catch (Exception ignored) { }
                final Bitmap got = bmp;
                main.post(new Runnable() {
                    public void run() {
                        if (got == null || !url.equals(artUrl) || running == null) return;
                        art = got;
                        widgetArt = Bitmap.createScaledBitmap(got, 192, 192 * got.getHeight() / Math.max(1, got.getWidth()), true);
                        refresh();
                    }
                });
            }
        }, "shelf-art").start();
    }

    private void shutdown() {
        NowPlayingWidget.push(this, null, null);
        if (wake.isHeld()) wake.release();
        if (wifi.isHeld()) wifi.release();
        session.setActive(false);
        stopForeground(true);
        notifications.cancel(NOTIFICATION);
        foreground = false;
        stopSelf();
    }

    @Override
    public void onDestroy() {
        if (running == this) running = null;
        if (wake.isHeld()) wake.release();
        if (wifi.isHeld()) wifi.release();
        session.release();
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) { return null; }
}
