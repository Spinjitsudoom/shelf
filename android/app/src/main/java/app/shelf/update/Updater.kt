package app.shelf.update

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.job.JobInfo
import android.app.job.JobScheduler
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInfo
import android.os.Build
import androidx.core.app.NotificationCompat
import app.shelf.R
import app.shelf.UpdateJob
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File

/** "v0.7.1" → 701, the versionCode releases are built with (major*10000 + minor*100 + patch). */
fun versionCode(tag: String): Int {
    val parts = tag.removePrefix("v").removePrefix("V").split('.')
    val n = (0 until 3).map { i -> parts.getOrNull(i)?.takeWhile(Char::isDigit)?.toIntOrNull() ?: 0 }
    return n[0] * 10000 + n[1] * 100 + n[2]
}

/** This app's download link in a GitHub release (Shelf-x.apk, not Shelf Lite's Shelf-x-Lite.apk), if it has one. */
fun apkAsset(release: JsonObject): String? = runCatching {
    release["assets"]?.jsonArray?.map { it.jsonObject }
        ?.lastOrNull { (it["name"] as? JsonPrimitive)?.contentOrNull?.let { n -> n.endsWith(".apk") && !n.endsWith("-Lite.apk") } == true }
        ?.let { (it["browser_download_url"] as? JsonPrimitive)?.contentOrNull }
}.getOrNull()

/**
 * Whether to hand updates to Android's installer screen rather than install them directly: Xiaomi's
 * MIUI turns down direct installs from apps ("Permission Denied"), as app stores like F-Droid found.
 */
fun prefersSystemInstaller(manufacturer: String): Boolean = manufacturer.equals("xiaomi", ignoreCase = true)

/** Only offer a download that is this app, newer than what's installed, and the version the release said. */
fun shouldOffer(mine: Int, latest: Int, apkPackage: String?, apkCode: Int?, myPackage: String): Boolean =
    latest > mine && apkPackage == myPackage && apkCode == latest

sealed interface UpdateResult {
    data object UpToDate : UpdateResult
    data class Ready(val version: String) : UpdateResult
    data class Failed(val message: String) : UpdateResult
    data object NotHere : UpdateResult
}

/**
 * Updates from GitHub, as the WebView app did: every 6 hours (and from Settings) it asks for
 * Shelf's latest release. A newer APK is downloaded in the background and a notification says
 * it's ready; tapping it opens Android's installer, which always asks first. Android only takes
 * an update signed with the same key, so nothing else can replace Shelf this way.
 */
class Updater(private val context: Context, private val http: OkHttpClient) {
    companion object {
        const val LATEST = "https://api.github.com/repos/Spinjitsudoom/shelf/releases/latest"
        private const val EVERY = 6 * 60 * 60 * 1000L
        const val JOB = 41 // the WebView app's job id, so its scheduled check carries over
        private const val NOTIFICATION = 2
        private const val CHANNEL = "updates"

        /** Releases ship the app as app.shelf; the preview build doesn't update itself. */
        fun enabled(context: Context) = context.packageName == "app.shelf"

        fun schedule(context: Context) {
            if (!enabled(context)) return
            val js = context.getSystemService(JobScheduler::class.java) ?: return
            if (js.allPendingJobs.any { it.id == JOB }) return
            js.schedule(JobInfo.Builder(JOB, ComponentName(context, UpdateJob::class.java))
                .setPeriodic(EVERY).setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY).setPersisted(true).build())
        }

        fun apk(context: Context) = File(context.cacheDir, "update.apk")
        fun clearNotification(context: Context) = context.getSystemService(NotificationManager::class.java).cancel(NOTIFICATION)
    }

    private val prefs = context.getSharedPreferences("updates", Context.MODE_PRIVATE)

    private fun get(url: String) = http.newCall(Request.Builder().url(url)
        .header("User-Agent", "ShelfAndroid (update check)").header("Accept", "application/vnd.github+json, application/octet-stream").build()).execute()

    @Suppress("DEPRECATION")
    private fun codeOf(info: PackageInfo?): Int? = info?.let { if (Build.VERSION.SDK_INT >= 28) it.longVersionCode.toInt() else it.versionCode }

    suspend fun check(force: Boolean): UpdateResult = withContext(Dispatchers.IO) {
        if (!enabled(context)) return@withContext UpdateResult.NotHere
        if (!force && System.currentTimeMillis() - prefs.getLong("checkedAt", 0) < EVERY) return@withContext UpdateResult.UpToDate
        try {
            val rel = get(LATEST).use { r ->
                if (!r.isSuccessful) return@withContext UpdateResult.Failed("GitHub answered ${r.code}.")
                Json.parseToJsonElement(r.body.string()).jsonObject
            }
            prefs.edit().putLong("checkedAt", System.currentTimeMillis()).apply()
            val tag = (rel["tag_name"] as? JsonPrimitive)?.contentOrNull ?: ""
            val latest = versionCode(tag)
            val pm = context.packageManager
            val mine = codeOf(pm.getPackageInfo(context.packageName, 0)) ?: 0
            val apk = apk(context)
            if (latest <= mine) { apk.delete(); return@withContext UpdateResult.UpToDate }
            val url = apkAsset(rel) ?: return@withContext UpdateResult.UpToDate
            val have = if (apk.exists()) pm.getPackageArchiveInfo(apk.path, 0) else null
            if (!shouldOffer(mine, latest, have?.packageName, codeOf(have), context.packageName)) {
                val part = File(context.cacheDir, "update.apk.part")
                get(url).use { r ->
                    if (!r.isSuccessful) return@withContext UpdateResult.Failed("The download failed (${r.code}).")
                    part.outputStream().use { out -> r.body.byteStream().copyTo(out) }
                }
                val got = pm.getPackageArchiveInfo(part.path, 0)
                if (!shouldOffer(mine, latest, got?.packageName, codeOf(got), context.packageName) || !part.renameTo(apk)) {
                    part.delete()
                    return@withContext UpdateResult.UpToDate // not the app we expected: leave it
                }
            }
            val version = tag.removePrefix("v").removePrefix("V")
            if (prefs.getInt("notified", 0) != latest) { notifyReady(version); prefs.edit().putInt("notified", latest).apply() }
            UpdateResult.Ready(version)
        } catch (e: Exception) {
            UpdateResult.Failed("Couldn’t reach GitHub. Check the connection and try again.")
        }
    }

    private fun notifyReady(version: String) {
        val nm = context.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CHANNEL, "App updates", NotificationManager.IMPORTANCE_DEFAULT))
        val tap = PendingIntent.getActivity(context, 0, Intent(context, UpdateActivity::class.java).setAction(UpdateActivity.ACTION_INSTALL),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        nm.notify(NOTIFICATION, NotificationCompat.Builder(context, CHANNEL).setSmallIcon(R.drawable.ic_stat)
            .setContentTitle("Shelf $version is ready").setContentText("Tap to install the update.")
            .setColor(0xFF2C4FD0.toInt()).setContentIntent(tap).setAutoCancel(true).build())
    }
}
