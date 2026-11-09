package app.shelf.ui.player

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.offset
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.util.VelocityTracker
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch
import kotlin.math.roundToInt

private const val THRESHOLD = 0.35f // of the width
private const val FLING_DP_PER_S = 1200f
private const val RUBBER = 0.3f // how far it gives when there's nothing to swipe to

/**
 * Swipe left for the next song, right for the one before. The neighbour slides in with your
 * finger and snaps over when you let go past a third of the way (or flick), with a tick;
 * otherwise everything springs back. With no song on that side it only gives a little.
 */
@Composable
fun SwipeToSkip(
    previous: (@Composable () -> Unit)?,
    current: @Composable () -> Unit,
    next: (@Composable () -> Unit)?,
    onPrevious: () -> Unit,
    onNext: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val offset = remember { Animatable(0f) }
    val scope = rememberCoroutineScope()
    val haptics = LocalHapticFeedback.current
    val flingPx = with(LocalDensity.current) { FLING_DP_PER_S.dp.toPx() }
    Box(
        modifier.clipToBounds().pointerInput(previous != null, next != null) {
            val tracker = VelocityTracker()
            detectHorizontalDragGestures(
                onDragStart = { tracker.resetTracking() },
                onHorizontalDrag = { change, delta ->
                    tracker.addPosition(change.uptimeMillis, change.position)
                    val blocked = (delta < 0 && offset.value <= 0f && next == null) || (delta > 0 && offset.value >= 0f && previous == null)
                    scope.launch { offset.snapTo(offset.value + if (blocked) delta * RUBBER else delta) }
                },
                onDragEnd = {
                    val width = size.width.toFloat()
                    val v = tracker.calculateVelocity().x
                    val goNext = next != null && (offset.value < -width * THRESHOLD || (v < -flingPx && offset.value < 0f))
                    val goPrev = previous != null && (offset.value > width * THRESHOLD || (v > flingPx && offset.value > 0f))
                    scope.launch {
                        when {
                            goNext -> { offset.animateTo(-width, tween(180)); haptics.performHapticFeedback(HapticFeedbackType.SegmentTick); onNext(); offset.snapTo(0f) }
                            goPrev -> { offset.animateTo(width, tween(180)); haptics.performHapticFeedback(HapticFeedbackType.SegmentTick); onPrevious(); offset.snapTo(0f) }
                            else -> offset.animateTo(0f, spring(dampingRatio = 0.8f, stiffness = 500f))
                        }
                    }
                },
                onDragCancel = { scope.launch { offset.animateTo(0f, spring()) } },
            )
        },
    ) {
        androidx.compose.foundation.layout.BoxWithConstraints(Modifier.fillMaxSize()) {
            val w = constraints.maxWidth
            val x = offset.value.roundToInt()
            Box(Modifier.fillMaxSize().offset { IntOffset(x, 0) }) { current() }
            if (previous != null && x > 0) Box(Modifier.fillMaxSize().offset { IntOffset(x - w, 0) }) { previous() }
            if (next != null && x < 0) Box(Modifier.fillMaxSize().offset { IntOffset(x + w, 0) }) { next() }
        }
    }
}
