package app.shelf.ui.start

import android.Manifest
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import app.shelf.ui.theme.Shelf

private val xiaomi get() = Build.MANUFACTURER.lowercase().let { "xiaomi" in it || "redmi" in it || "poco" in it }

/** Whether to ask (once): Android may stop Shelf in the background, or it can't show its notification. */
fun needsOnboarding(context: Context): Boolean {
    val prefs = context.getSharedPreferences("shelf", Context.MODE_PRIVATE)
    if (prefs.getBoolean("onboarded", false)) return false
    val pm = context.getSystemService(PowerManager::class.java)
    val notifications = Build.VERSION.SDK_INT < 33 ||
        context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == android.content.pm.PackageManager.PERMISSION_GRANTED
    return xiaomi || !pm.isIgnoringBatteryOptimizations(context.packageName) || !notifications
}

/** First run: why Shelf asks to run in the background (and show its notification), asked once. */
@Composable
fun Onboarding(onDone: () -> Unit) {
    val context = LocalContext.current
    fun finish() { context.getSharedPreferences("shelf", Context.MODE_PRIVATE).edit().putBoolean("onboarded", true).apply(); onDone() }
    fun background() {
        val pm = context.getSystemService(PowerManager::class.java)
        runCatching {
            if (!pm.isIgnoringBatteryOptimizations(context.packageName))
                context.startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:${context.packageName}")))
        }
        if (xiaomi) {
            // MIUI also has Autostart, which it checks before letting an app run in the background.
            val tries = listOf(Intent().setComponent(ComponentName("com.miui.securitycenter", "com.miui.permcenter.autostart.AutoStartManagementActivity")),
                Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:${context.packageName}")))
            tries.firstOrNull { runCatching { context.startActivity(it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }.isSuccess }
        }
        finish()
    }
    val notify = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { background() }
    Column(Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding().padding(28.dp), verticalArrangement = Arrangement.spacedBy(16.dp, androidx.compose.ui.Alignment.CenterVertically)) {
        Text("Keep the music playing", style = MaterialTheme.typography.displaySmall, color = Shelf.colors.ink)
        Text("To save battery, Android can stop apps in the background, which would stop your music with the screen off. " +
            "Let Shelf run without battery restrictions" + (if (Build.VERSION.SDK_INT >= 33) ", and show what's playing in a notification." else "."),
            style = MaterialTheme.typography.bodyLarge, color = Shelf.colors.ink2)
        if (xiaomi) Text("On this phone, also turn on Autostart for Shelf, and set its battery saver to “No restrictions”, or MIUI may still stop it.",
            style = MaterialTheme.typography.bodyMedium, color = Shelf.colors.ink2)
        Button(onClick = {
            if (Build.VERSION.SDK_INT >= 33) notify.launch(Manifest.permission.POST_NOTIFICATIONS) else background()
        }, modifier = Modifier.fillMaxWidth(), colors = ButtonDefaults.buttonColors(containerColor = Shelf.colors.cobalt, contentColor = Shelf.colors.cobaltInk)) {
            Text("Allow")
        }
        TextButton(onClick = ::finish, modifier = Modifier.fillMaxWidth()) { Text("Not now", color = Shelf.colors.ink2) }
    }
}
