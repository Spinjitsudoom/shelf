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
    val dataQuality: String = "auto",      // auto (lossless made smaller, the rest as is), or a fixed quality
    val normalize: Boolean = true,
    val loudness: String = "normal",       // loud, normal, quiet
    val theme: String = "dark",            // dark, light, system
    val format: String = "cd",             // cd, vinyl
    val eqEnabled: Boolean = false,
    val eqPreset: String = "Flat",         // a preset's name, or "Custom"
    val eqGains: List<Double> = List(6) { 0.0 }, // dB at 60, 150, 400, 1000, 2400 and 15000 Hz
    val balance: Float = 0f,               // −1 left … 1 right
    val mono: Boolean = false,
)

class SettingsStore(private val prefs: SharedPreferences) {
    private val json = Json { ignoreUnknownKeys = true; encodeDefaults = true }
    private val _settings = MutableStateFlow(load())
    val settings: StateFlow<Settings> = _settings

    private fun load(): Settings = prefs.getString("settings", null)
        ?.let { runCatching { json.decodeFromString(Settings.serializer(), it) }.getOrNull() } ?: Settings()

    fun update(transform: (Settings) -> Settings) {
        val next = transform(_settings.value)
        prefs.edit().putString("settings", json.encodeToString(Settings.serializer(), next)).apply()
        _settings.value = next
    }
}

/** The settings, for screens (CD or vinyl covers and so on). */
val LocalSettings = staticCompositionLocalOf { Settings() }
