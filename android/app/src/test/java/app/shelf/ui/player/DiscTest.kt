package app.shelf.ui.player

import androidx.compose.foundation.layout.size
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.unit.dp
import androidx.test.ext.junit.runners.AndroidJUnit4
import app.shelf.settings.LocalSettings
import app.shelf.settings.Settings
import app.shelf.ui.theme.ShelfTheme
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class DiscTest {
    @get:Rule val rule = createComposeRule()

    private fun show(format: String) = rule.setContent {
        ShelfTheme { CompositionLocalProvider(LocalSettings provides Settings(format = format)) { Disc(null, spinning = false, Modifier.size(200.dp)) } }
    }

    @Test fun cdSettingShowsACd() {
        show("cd")
        rule.onNodeWithTag("disc-cd").assertExists()
        rule.onNodeWithTag("disc-record").assertDoesNotExist()
    }

    @Test fun vinylSettingShowsARecord() {
        show("vinyl")
        rule.onNodeWithTag("disc-record").assertExists()
        rule.onNodeWithTag("disc-cd").assertDoesNotExist()
    }

    private fun deck(format: String, playing: Boolean) = rule.setContent {
        ShelfTheme { CompositionLocalProvider(LocalSettings provides Settings(format = format)) {
            Deck(app.shelf.data.Track(1, "Song", "Band", album = "Album", albumId = 1), null, playing, Modifier.size(300.dp))
        } }
    }

    @Test fun vinylDeckHasATonearm() {
        deck("vinyl", playing = true)
        rule.onNodeWithTag("tonearm").assertExists()
    }

    @Test fun cdDeckHasNoTonearm() {
        deck("cd", playing = true)
        rule.onNodeWithTag("tonearm").assertDoesNotExist()
    }
}
