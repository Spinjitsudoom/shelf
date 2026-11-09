package app.shelf.connect

import android.content.Context
import android.os.Build
import android.provider.Settings
import java.security.SecureRandom

private val ID = Regex("^[A-Za-z0-9_-]{8,64}$")
private const val ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"

/** How this phone shows up in other devices' lists: a lasting id, its name, and phone or tablet. */
class DeviceIdentity(private val load: () -> String?, private val save: (String) -> Unit, val name: String, val kind: String) {
    val id: String get() = load()?.takeIf { ID.matches(it) } ?: renew()

    /** A new id (when another device already has this one). */
    fun renew(): String {
        val r = SecureRandom()
        return String(CharArray(22) { ALPHABET[r.nextInt(ALPHABET.length)] }).also(save)
    }

    companion object {
        fun of(context: Context): DeviceIdentity {
            val prefs = context.getSharedPreferences("connect", Context.MODE_PRIVATE)
            val name = runCatching { Settings.Global.getString(context.contentResolver, Settings.Global.DEVICE_NAME) }.getOrNull()
                ?.takeIf { it.isNotBlank() } ?: Build.MODEL ?: "Android phone"
            val kind = if (context.resources.configuration.smallestScreenWidthDp >= 600) "tablet" else "phone"
            return DeviceIdentity({ prefs.getString("id", null) }, { prefs.edit().putString("id", it).apply() }, name, kind)
        }
    }
}
