package app.shelf.ui.player

import androidx.compose.foundation.layout.height
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithContentDescription
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.swipe
import androidx.compose.ui.unit.dp
import androidx.test.ext.junit.runners.AndroidJUnit4
import app.shelf.connect.tr
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class QueueListTest {
    @get:Rule val rule = createComposeRule()
    private val moves = mutableListOf<Pair<Int, Int>>()

    /** Five songs, the second playing. */
    private fun show(canReorder: Boolean = true) = rule.setContent {
        QueueList((1..5).map { tr(it) }, index = 1, canReorder = canReorder, onPlay = {}, onMove = { f, t -> moves += f to t },
            leading = {}, modifier = Modifier.height(600.dp))
    }

    @Test fun handlesOnlyOnUpNext() {
        show()
        rule.onAllNodesWithContentDescription("Drag to move", substring = true).assertCountEquals(3)
        rule.onAllNodesWithContentDescription("Drag to move Song 2").assertCountEquals(0)
        rule.onAllNodesWithContentDescription("Drag to move Song 1").assertCountEquals(0)
    }

    @Test fun draggingASongDownMovesIt() {
        show()
        // The handle itself (the tappable row merges it in otherwise, and its centre is the title).
        val handle = rule.onNodeWithContentDescription("Drag to move Song 3", useUnmergedTree = true)
        // Down to where Song 5 is: two rows.
        val by = rule.onNodeWithContentDescription("Drag to move Song 5", useUnmergedTree = true).fetchSemanticsNode().boundsInRoot.center.y -
            handle.fetchSemanticsNode().boundsInRoot.center.y
        handle.performTouchInput { swipe(center, center + Offset(0f, by), 1000) }
        rule.waitForIdle()
        assertEquals(listOf(2 to 4), moves)
    }

    @Test fun noDraggingWhileShuffled() {
        show(canReorder = false)
        rule.onAllNodesWithContentDescription("Drag to move", substring = true).assertCountEquals(0)
        rule.onNodeWithText("Turn off shuffle to change the order").assertExists()
    }
}
