package app.shelf.ui.player

import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.test.ext.junit.runners.AndroidJUnit4
import app.shelf.connect.ConnectUi
import app.shelf.connect.DeviceInfo
import app.shelf.ui.theme.ShelfTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class DevicesSheetTest {
    @get:Rule val rule = createComposeRule()
    private val ui = ConnectUi(connected = true, selfId = "me", activeId = "pc",
        devices = listOf(DeviceInfo("pc", "Desk", "computer"), DeviceInfo("me", "Redmi", "phone"), DeviceInfo("tv", "Living room", "tv")))

    @Test fun listsThisPhoneFirstAndTicksActive() {
        rule.setContent { ShelfTheme { DeviceList(ui, {}) } }
        val names = rule.onAllNodesWithTag("device-name", useUnmergedTree = true).fetchSemanticsNodes().map { it.config[SemanticsProperties.Text].joinToString() }
        assertEquals(listOf("This phone", "Desk", "Living room"), names)
        rule.onNodeWithText("Playing").assertExists()
    }

    @Test fun pickingSendsTransfer() {
        var picked: String? = null
        rule.setContent { ShelfTheme { DeviceList(ui, { picked = it }) } }
        rule.onNodeWithText("Living room").performClick()
        assertEquals("tv", picked)
        rule.onNodeWithText("This phone").performClick()
        assertEquals("me", picked)
    }

    @Test fun notConnectedSaysSo() {
        rule.setContent { ShelfTheme { DeviceList(ui.copy(connected = false), {}) } }
        rule.onNodeWithText("Can’t reach the server to see your other devices").assertExists()
    }
}
