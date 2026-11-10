package app.shelf.ui.browse

import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.ext.junit.runners.AndroidJUnit4
import app.shelf.data.Track
import app.shelf.playback.TransitionChoice
import app.shelf.ui.theme.ShelfTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class TransitionSheetTest {
    @get:Rule val rule = createComposeRule()
    private val a = Track(1, "Opening", "Band", albumId = 1, duration = 200.0)
    private val b = Track(2, "Closer", "Band", albumId = 1, duration = 200.0)

    @Test fun pickingAStyleSavesIt() {
        var saved: TransitionChoice? = null
        rule.setContent { ShelfTheme { TransitionPicker(a, b, null, editable = true, onSave = { saved = it }) } }
        rule.onNodeWithText("Bass swap").performClick()
        assertEquals(TransitionChoice("swap"), saved)
    }

    @Test fun readOnlyJustDescribes() {
        rule.setContent { ShelfTheme { TransitionPicker(a, b, null, editable = false, onSave = {}) } }
        rule.onNodeWithText("Fade: 8 second crossfade").assertExists()
        rule.onNodeWithText("Bass swap").assertDoesNotExist()
    }
}
