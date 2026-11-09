package app.shelf.ui.player

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.swipe
import androidx.compose.ui.unit.dp
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class SwipeToSkipTest {
    @get:Rule val rule = createComposeRule()
    private var nexts = 0
    private var prevs = 0

    private fun show(hasPrev: Boolean = true, hasNext: Boolean = true) {
        val page: @Composable (String) -> Unit = { Box(Modifier.size(400.dp, 100.dp)) { Text(it) } }
        rule.setContent {
            SwipeToSkip(
                previous = if (hasPrev) ({ page("prev") }) else null,
                current = { page("now") },
                next = if (hasNext) ({ page("next") }) else null,
                onPrevious = { prevs++ }, onNext = { nexts++ },
                modifier = Modifier.size(400.dp, 100.dp).testTag("swipe"),
            )
        }
    }

    /** Drag across `fraction` of the width (negative: to the left) over `ms`. */
    private fun drag(fraction: Float, ms: Long) {
        rule.onNodeWithTag("swipe").performTouchInput {
            val y = centerY
            swipe(Offset(centerX, y), Offset(centerX + width * fraction, y), ms)
        }
        rule.waitForIdle()
    }

    @Test fun swipeLeftPastThresholdGoesNext() { show(); drag(-0.45f, 600); assertEquals(1, nexts); assertEquals(0, prevs) }

    @Test fun swipeRightGoesPrevious() { show(); drag(0.45f, 600); assertEquals(1, prevs); assertEquals(0, nexts) }

    @Test fun shortSwipeDoesNothing() { show(); drag(-0.2f, 1500); assertEquals(0, nexts); assertEquals(0, prevs) }

    @Test fun flingSkipsEvenWhenShort() { show(); drag(-0.2f, 50); assertEquals(1, nexts) }

    @Test fun swipeAtQueueEndSpringsBack() { show(hasNext = false); drag(-0.6f, 400); assertEquals(0, nexts); assertEquals(0, prevs) }
}
