package app.shelf.settings

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class SettingsStoreTest {
    @Test fun settingsPersistAndEmit() {
        val prefs = ApplicationProvider.getApplicationContext<Context>().getSharedPreferences("settings-test", Context.MODE_PRIVATE)
        prefs.edit().clear().commit()
        val store = SettingsStore(prefs)
        assertEquals(Settings(), store.settings.value) // the defaults
        store.update { it.copy(theme = "light", format = "vinyl", loudness = "quiet") }
        assertEquals("vinyl", store.settings.value.format)
        val again = SettingsStore(prefs)
        assertEquals(Settings(theme = "light", format = "vinyl", loudness = "quiet"), again.settings.value)
    }

    /** Converted copies from the server could be unplayable (0.7.x), so the old defaults move to Original, once. */
    @Test fun oldDefaultsMoveToOriginalOnce() {
        val prefs = ApplicationProvider.getApplicationContext<Context>().getSharedPreferences("settings-old", Context.MODE_PRIVATE)
        prefs.edit().clear().putString("settings", """{"wifiQuality":"original","dataQuality":"auto","downloadQuality":"veryhigh","theme":"light"}""").commit()
        val store = SettingsStore(prefs)
        assertEquals("original", store.settings.value.dataQuality)
        assertEquals("original", store.settings.value.downloadQuality)
        assertEquals("light", store.settings.value.theme)
        assertTrue(store.movedToOriginal)
        assertFalse(SettingsStore(prefs).movedToOriginal) // only the first time

        // A quality picked on purpose stays.
        prefs.edit().clear().putString("settings", """{"dataQuality":"normal","downloadQuality":"low"}""").commit()
        val picked = SettingsStore(prefs).settings.value
        assertEquals("normal", picked.dataQuality)
        assertEquals("low", picked.downloadQuality)
    }

    @Test fun newPhonesStartWithOriginal() {
        assertEquals("original", Settings().dataQuality)
        assertEquals("original", Settings().downloadQuality)
    }
}
