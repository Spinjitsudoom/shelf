package app.shelf.data

import android.content.SharedPreferences

/** The chosen server and the sign-in for it, kept between launches. */
class ServerStore(private val prefs: SharedPreferences) {
    var server: String?
        get() = prefs.getString("server", null)
        set(v) = prefs.edit().putString("server", v).apply()
    var token: String?
        get() = prefs.getString("token", null)
        set(v) = prefs.edit().putString("token", v).apply()
    var username: String?
        get() = prefs.getString("username", null)
        set(v) = prefs.edit().putString("username", v).apply()

    /** Signed in with this (native) app at least once. The WebView app it replaces never set it. */
    var native: Boolean
        get() = prefs.getBoolean("native", false)
        set(v) = prefs.edit().putBoolean("native", v).apply()

    /** Addresses of this server the app has moved away from (to its secure address): requests to them go to [server]. */
    val formerServers: Set<String>
        get() = prefs.getStringSet("formerServers", emptySet()) ?: emptySet()

    /** The same server at another address (its secure one), signed in as before. */
    fun moveTo(url: String) {
        val old = server
        prefs.edit().putString("server", url)
            .putStringSet("formerServers", formerServers + listOfNotNull(old) - url).apply()
    }

    /** Forget the sign-in, keep the server (so signing in again is one step). */
    fun signOut() = prefs.edit().remove("token").apply()
}
