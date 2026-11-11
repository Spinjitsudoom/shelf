package app.shelf.settings

import android.content.SharedPreferences
import androidx.compose.runtime.staticCompositionLocalOf
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/** This phone's listening and appearance settings (the web app's are per device too). */
@Serializable
data class Settings(
    val wifiQuality: String = "original",  // original, veryhigh, high, normal, low
    val dataQuality: String = "original",  // original, auto (lossless made smaller, the rest as is), or a fixed quality
    val normalize: Boolean = true,
    val loudness: String = "normal",       // loud, normal, quiet
    val theme: String = "dark",            // dark, light, system
    val format: String = "cd",             // cd, vinyl
    val eqEnabled: Boolean = false,
    val eqPreset: String = "Flat",         // a preset's name, or "Custom"
    val eqGains: List<Double> = List(6) { 0.0 }, // dB at 60, 150, 400, 1000, 2400 and 15000 Hz
    val balance: Float = 0f,               // −1 left … 1 right
    val mono: Boolean = false,
    val autoplay: Boolean = true,          // similar songs when the queue runs out
    val privateSession: Boolean = false,   // this phone's listening kept out of friend activity
    val spinDisc: Boolean = true,
    val visualizer: Boolean = true,        // the ring of bars around the disc on Now Playing
    val deviceName: String = "",           // empty: the phone's own name
    val downloadQuality: String = "original",
    val crossfade: Int = 0,                // seconds, 0 = off (Mix playlists use their own transitions)
    val crossfadeAlbums: Boolean = false,  // crossfade between songs of the same album too
    val qualityVersion: Int = 1,           // 1: Original is the default everywhere (settings saved before have no number)
)

class SettingsStore(private val prefs: SharedPreferences) {
    private val json = Json { ignoreUnknownKeys = true; encodeDefaults = true }
    private val saved = prefs.getString("settings", null)

    /**
     * True the first time settings saved before 0.7.5 are opened. Their converted copies from the
     * server could be unplayable on Android, so the old defaults (Automatic on mobile data, 320 kbps
     * downloads) became Original; downloads made as copies are then fetched again.
     */
    val movedToOriginal = saved != null && "\"qualityVersion\"" !in saved

    private val _settings = MutableStateFlow(load())
    val settings: StateFlow<Settings> = _settings

    init { if (movedToOriginal) update { it } }

    private fun load(): Settings {
        val s = saved?.let { runCatching { json.decodeFromString(Settings.serializer(), it) }.getOrNull() } ?: Settings()
        if (!movedToOriginal) return s
        return s.copy(dataQuality = if (s.dataQuality == "auto") "original" else s.dataQuality,
            downloadQuality = if (s.downloadQuality == "veryhigh") "original" else s.downloadQuality, qualityVersion = 1)
    }

    fun update(transform: (Settings) -> Settings) {
        val next = transform(_settings.value)
        prefs.edit().putString("settings", json.encodeToString(Settings.serializer(), next)).apply()
        _settings.value = next
    }
}

/** The settings, for screens (CD or vinyl covers and so on). */
val LocalSettings = staticCompositionLocalOf { Settings() }
