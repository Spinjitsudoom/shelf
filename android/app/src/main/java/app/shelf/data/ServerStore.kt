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

    /** Forget the sign-in, keep the server (so signing in again is one step). */
    fun signOut() = prefs.edit().remove("token").apply()
}
