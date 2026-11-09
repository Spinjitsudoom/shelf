package app.shelf;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.job.JobInfo;
import android.app.job.JobScheduler;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.os.Build;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;

/**
 * New versions of the app: every six hours (and when the app opens, at most that often) it
 * asks GitHub for Shelf's latest release. A newer APK is downloaded in the background and a
 * notification says it's ready; tapping it opens UpdateActivity, which hands it to Android's
 * installer (Android always asks before installing). Android only accepts an update signed
 * with the same key as the installed app, so a download can't replace Shelf with anything else.
 */
final class Updater {
    static final String LATEST = "https://api.github.com/repos/Spinjitsudoom/shelf/releases/latest";
    private static final long EVERY = 6 * 60 * 60 * 1000L;
    private static final int JOB = 41;
    private static final int NOTIFICATION = 2;
    private static final String CHANNEL = "updates";

    private Updater() { }

    /** Check now if the last check was long enough ago, on a background thread. */
    static void checkSoon(final Context context) {
        final Context ctx = context.getApplicationContext();
        if (System.currentTimeMillis() - prefs(ctx).getLong("checkedAt", 0) < EVERY) return;
        new Thread(new Runnable() { public void run() { check(ctx); } }, "shelf-update-check").start();
    }

    /** The periodic background check (UpdateJob runs it, even when Shelf isn't open). */
    static void schedule(Context context) {
        JobScheduler js = (JobScheduler) context.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        if (js == null) return;
        for (JobInfo j : js.getAllPendingJobs()) if (j.getId() == JOB) return;
        js.schedule(new JobInfo.Builder(JOB, new ComponentName(context, UpdateJob.class))
            .setPeriodic(EVERY)
            .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
            .setPersisted(true)
            .build());
    }

    /** "v0.7.1" -> 701, the versionCode releases are built with (major*10000 + minor*100 + patch). */
    static int code(String tag) {
        String[] p = tag.replaceFirst("^[vV]", "").split("\\.");
        int[] n = new int[3];
        for (int i = 0; i < 3 && i < p.length; i++) {
            String digits = p[i].replaceAll("[^0-9].*$", "");
            n[i] = digits.isEmpty() ? 0 : Integer.parseInt(digits);
        }
        return n[0] * 10000 + n[1] * 100 + n[2];
    }

    @SuppressWarnings("deprecation")
    static synchronized void check(Context ctx) {
        SharedPreferences prefs = prefs(ctx);
        try {
            JSONObject rel = new JSONObject(new String(get(LATEST), "UTF-8"));
            prefs.edit().putLong("checkedAt", System.currentTimeMillis()).apply();
            String tag = rel.optString("tag_name", "");
            int latest = code(tag);
            PackageManager pm = ctx.getPackageManager();
            int mine = pm.getPackageInfo(ctx.getPackageName(), 0).versionCode;
            File apk = new File(ctx.getCacheDir(), "update.apk");
            if (latest <= mine) { apk.delete(); return; }

            String url = null;
            JSONArray assets = rel.optJSONArray("assets");
            for (int i = 0; assets != null && i < assets.length(); i++) {
                JSONObject a = assets.getJSONObject(i);
                if (a.optString("name").endsWith(".apk")) url = a.optString("browser_download_url");
            }
            if (url == null) return;

            PackageInfo have = apk.exists() ? pm.getPackageArchiveInfo(apk.getPath(), 0) : null;
            if (have == null || have.versionCode != latest) {
                File part = new File(ctx.getCacheDir(), "update.apk.part");
                download(url, part);
                PackageInfo got = pm.getPackageArchiveInfo(part.getPath(), 0);
                if (got == null || !ctx.getPackageName().equals(got.packageName) || got.versionCode != latest) {
                    part.delete();
                    return; // not the app we expected: leave it
                }
                if (!part.renameTo(apk)) return;
            }
            if (prefs.getInt("notified", 0) != latest) {
                notifyReady(ctx, tag.replaceFirst("^[vV]", ""));
                prefs.edit().putInt("notified", latest).apply();
            }
        } catch (Exception e) {
            android.util.Log.i("Shelf", "Update check failed: " + e);
        }
    }

    private static void notifyReady(Context ctx, String version) {
        NotificationManager nm = (NotificationManager) ctx.getSystemService(Context.NOTIFICATION_SERVICE);
        if (Build.VERSION.SDK_INT >= 26) {
            nm.createNotificationChannel(new NotificationChannel(CHANNEL, "App updates", NotificationManager.IMPORTANCE_DEFAULT));
        }
        Intent open = new Intent(ctx, UpdateActivity.class).setAction(UpdateActivity.ACTION_INSTALL);
        int flags = PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_IMMUTABLE : 0);
        PendingIntent tap = PendingIntent.getActivity(ctx, 0, open, flags);
        @SuppressWarnings("deprecation")
        Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(ctx, CHANNEL) : new Notification.Builder(ctx);
        b.setSmallIcon(R.drawable.ic_stat)
            .setContentTitle("Shelf " + version + " is ready")
            .setContentText("Tap to install the update.")
            .setColor(0xFF2C4FD0)
            .setContentIntent(tap)
            .setAutoCancel(true);
        nm.notify(NOTIFICATION, b.build());
    }

    static void clearNotification(Context ctx) {
        ((NotificationManager) ctx.getSystemService(Context.NOTIFICATION_SERVICE)).cancel(NOTIFICATION);
    }

    private static SharedPreferences prefs(Context ctx) {
        return ctx.getSharedPreferences("updates", Context.MODE_PRIVATE);
    }

    private static HttpURLConnection open(String url) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        c.setConnectTimeout(20000);
        c.setReadTimeout(60000);
        c.setInstanceFollowRedirects(true);
        c.setRequestProperty("User-Agent", "ShelfAndroid (update check)");
        c.setRequestProperty("Accept", "application/vnd.github+json, application/octet-stream");
        return c;
    }

    private static byte[] get(String url) throws Exception {
        HttpURLConnection c = open(url);
        try (InputStream in = c.getInputStream(); ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            byte[] buf = new byte[16384];
            for (int n; (n = in.read(buf)) > 0; ) out.write(buf, 0, n);
            return out.toByteArray();
        } finally {
            c.disconnect();
        }
    }

    private static void download(String url, File dest) throws Exception {
        HttpURLConnection c = open(url);
        try (InputStream in = c.getInputStream(); OutputStream out = new FileOutputStream(dest)) {
            byte[] buf = new byte[65536];
            for (int n; (n = in.read(buf)) > 0; ) out.write(buf, 0, n);
        } finally {
            c.disconnect();
        }
    }
}
