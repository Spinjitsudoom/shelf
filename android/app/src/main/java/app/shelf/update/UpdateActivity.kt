package app.shelf.update

import android.app.Activity
import android.app.PendingIntent
import android.content.Intent
import android.content.pm.PackageInstaller
import android.os.Build
import android.os.Bundle
import android.widget.Toast
import app.shelf.ShelfApp
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

/**
 * Installs a downloaded update (from the "Shelf X is ready" notification, or Settings). It has no
 * screen of its own: it hands the APK to Android's installer, which asks "update this app?".
 */
class UpdateActivity : Activity() {
    companion object {
        const val ACTION_INSTALL = "app.shelf.INSTALL_UPDATE"
        private const val ACTION_STATUS = "app.shelf.UPDATE_STATUS"
    }

    override fun onCreate(state: Bundle?) { super.onCreate(state); handle(intent) }
    override fun onNewIntent(intent: Intent) { super.onNewIntent(intent); handle(intent) }

    private fun handle(intent: Intent?) = when (intent?.action) {
        ACTION_STATUS -> status(intent)
        ACTION_INSTALL -> install()
        else -> finish()
    }

    private fun install() {
        val apk = Updater.apk(this)
        if (!apk.exists()) {
            Toast.makeText(this, "The update isn’t downloaded any more. Shelf will fetch it again.", Toast.LENGTH_LONG).show()
            val app = application as ShelfApp
            CoroutineScope(Dispatchers.Main).launch { Updater(applicationContext, app.container.plainHttp).check(force = true) }
            finish(); return
        }
        Updater.clearNotification(this)
        try {
            val installer = packageManager.packageInstaller
            val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL).apply { setAppPackageName(packageName) }
            val id = installer.createSession(params)
            installer.openSession(id).use { session ->
                apk.inputStream().use { input -> session.openWrite("shelf.apk", 0, apk.length()).use { out -> input.copyTo(out); session.fsync(out) } }
                val back = Intent(this, UpdateActivity::class.java).setAction(ACTION_STATUS)
                val flags = PendingIntent.FLAG_UPDATE_CURRENT or (if (Build.VERSION.SDK_INT >= 31) PendingIntent.FLAG_MUTABLE else 0)
                session.commit(PendingIntent.getActivity(this, 1, back, flags).intentSender)
            }
        } catch (e: Exception) {
            Toast.makeText(this, "Couldn’t install the update: ${e.message}", Toast.LENGTH_LONG).show()
            finish()
        }
    }

    @Suppress("DEPRECATION")
    private fun status(intent: Intent) {
        val status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE)
        if (status == PackageInstaller.STATUS_PENDING_USER_ACTION) {
            intent.getParcelableExtra<Intent>(Intent.EXTRA_INTENT)?.let { startActivity(it) } // Android's "update this app?" screen
            return
        }
        if (status != PackageInstaller.STATUS_SUCCESS && status != PackageInstaller.STATUS_FAILURE_ABORTED) {
            val msg = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE)
            Toast.makeText(this, "The update didn’t install" + (msg?.let { ": $it" } ?: ""), Toast.LENGTH_LONG).show()
        }
        finish()
    }
}
