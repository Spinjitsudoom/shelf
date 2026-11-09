package app.shelf.settings

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertEquals
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
}
