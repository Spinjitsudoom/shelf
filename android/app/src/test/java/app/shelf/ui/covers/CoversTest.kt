package app.shelf.ui.covers

import androidx.compose.foundation.layout.size
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.runner.RunWith
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.unit.dp
import app.shelf.ui.theme.ShelfTheme
import org.junit.Rule
import org.junit.Test

/** Runs on the computer under Robolectric (MIUI asks for a tap to install test apps over USB). */
@RunWith(AndroidJUnit4::class)
class CoversTest {
    @get:Rule val rule = createComposeRule()

    @Test
    fun coverWithoutArtShowsTitle() {
        rule.setContent { ShelfTheme { CaseCover(url = null, title = "Abbey Road", color = Color(0xff364fc7), modifier = Modifier.size(200.dp)) } }
        rule.onNodeWithText("Abbey Road").assertExists()
    }

    @Test
    fun vinylWithoutArtShowsTitle() {
        rule.setContent { ShelfTheme { CaseCover(url = null, title = "Rumours", color = Color(0xff7a4d2c), modifier = Modifier.size(200.dp), vinyl = true) } }
        rule.onNodeWithText("Rumours").assertExists()
    }

    @Test
    fun tapeShowsName() {
        rule.setContent { ShelfTheme { TapeCover(name = "Shelf Mix 1", color = Color(0xffe8590c), covers = emptyList(), modifier = Modifier.size(200.dp)) } }
        rule.onNodeWithText("Shelf Mix 1").assertExists()
    }
}
