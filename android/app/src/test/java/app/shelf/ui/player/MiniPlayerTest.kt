package app.shelf.ui.player

import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.semantics.SemanticsActions
import androidx.test.ext.junit.runners.AndroidJUnit4
import app.shelf.data.Track
import app.shelf.playback.PlayerUi
import app.shelf.ui.theme.ShelfTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class MiniPlayerTest {
    @get:Rule val rule = createComposeRule()

    private fun state(title: String) = PlayerUi(current = Track(1, title, "Måneskin", albumId = 1, duration = 200.0), playing = true, durationMs = 200_000)

    @Test fun longTitleStaysOneLine() {
        val long = "Måneskin 日本語 " + "a very long song title that goes on and on ".repeat(5)
        rule.setContent { ShelfTheme { MiniPlayer(state(long), { null }, {}, {}, {}, {}) } }
        val node = rule.onNodeWithTag("mini-title", useUnmergedTree = true).fetchSemanticsNode()
        val layouts = mutableListOf<TextLayoutResult>()
        node.config[SemanticsActions.GetTextLayoutResult].action!!.invoke(layouts)
        assertEquals(1, layouts.first().lineCount)
    }

    @Test fun tapOpensNowPlaying() {
        var opened = false
        rule.setContent { ShelfTheme { MiniPlayer(state("Song"), { null }, {}, {}, {}, { opened = true }) } }
        rule.onNodeWithTag("mini-player").performClick()
        assertTrue(opened)
    }
}
