package app.shelf.ui.browse

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.shelf.R
import app.shelf.data.Track
import app.shelf.playback.PARTS
import app.shelf.playback.STYLES
import app.shelf.playback.STYLE_HELP
import app.shelf.playback.STYLE_LABEL
import app.shelf.playback.TransitionChoice
import app.shelf.playback.autoStyle
import app.shelf.playback.describe
import app.shelf.playback.plan
import app.shelf.ui.theme.Shelf
import kotlin.math.roundToInt

/** Between two songs of a Mix playlist: how the first hands over to the second. Tap to change it. */
@Composable
fun TransitionPill(cur: Track, nxt: Track, onClick: () -> Unit) {
    val choice = TransitionChoice.of(cur.transition)
    val label = if (choice.style == "auto") "Auto: ${STYLE_LABEL[autoStyle(cur, nxt)]}" else STYLE_LABEL[choice.style] ?: "Auto"
    val custom = choice != TransitionChoice(choice.style)
    Box(Modifier.fillMaxWidth().padding(vertical = 2.dp), contentAlignment = Alignment.Center) {
        HorizontalDivider(color = Shelf.colors.rule, modifier = Modifier.padding(horizontal = 72.dp))
        Surface(onClick = onClick, shape = RoundedCornerShape(50), color = Shelf.colors.tray, border = BorderStroke(1.dp, Shelf.colors.cobalt.copy(alpha = .6f))) {
            Row(Modifier.padding(horizontal = 12.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                Icon(painterResource(R.drawable.ic_shuffle), null, tint = Shelf.colors.cobalt, modifier = Modifier.size(14.dp))
                Spacer(Modifier.width(6.dp))
                Text(label + if (custom) ", fine-tuned" else "", style = MaterialTheme.typography.labelMedium, color = Shelf.colors.cobalt)
            }
        }
    }
}

/** How [cur] hands over to [nxt]: the styles to pick from, and the parts to fine-tune (when the playlist can be edited). */
@Composable
fun TransitionPicker(cur: Track, nxt: Track, setting: kotlinx.serialization.json.JsonElement?, editable: Boolean, onSave: (TransitionChoice) -> Unit) {
    val choice = TransitionChoice.of(setting)
    val shown = cur.copy(transition = setting)
    Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(bottom = 12.dp)) {
        Text("${cur.title} into ${nxt.title}", style = MaterialTheme.typography.titleMedium, color = Shelf.colors.ink, maxLines = 2, overflow = TextOverflow.Ellipsis,
            modifier = Modifier.padding(horizontal = 20.dp))
        Text(describe(shown, nxt, setting), style = MaterialTheme.typography.bodyMedium, color = Shelf.colors.cobalt, modifier = Modifier.padding(horizontal = 20.dp, vertical = 4.dp))
        if (!editable) {
            Text("Only the playlist's owner can change its transitions.", style = MaterialTheme.typography.bodySmall, color = Shelf.colors.ink2,
                modifier = Modifier.padding(horizontal = 20.dp, vertical = 6.dp))
            return@Column
        }
        HorizontalDivider(color = Shelf.colors.rule, modifier = Modifier.padding(vertical = 6.dp))
        STYLES.forEach { style ->
            val on = choice.style == style
            Row(Modifier.fillMaxWidth().clickable { onSave(TransitionChoice(style)) }.padding(horizontal = 20.dp, vertical = 9.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(STYLE_LABEL.getValue(style) + if (style == "auto") " (${STYLE_LABEL[autoStyle(cur, nxt)]} here)" else "",
                        style = MaterialTheme.typography.titleSmall, color = if (on) Shelf.colors.cobalt else Shelf.colors.ink)
                    Text(STYLE_HELP.getValue(style), style = MaterialTheme.typography.bodySmall, color = Shelf.colors.ink2)
                }
                if (on) Icon(painterResource(R.drawable.ic_check), "Chosen", tint = Shelf.colors.cobalt)
            }
        }
        if (choice.style == "cut") return@Column
        // Fine-tune: the web's transition editor's parts.
        HorizontalDivider(color = Shelf.colors.rule, modifier = Modifier.padding(vertical = 6.dp))
        Text("Fine-tune", style = MaterialTheme.typography.titleMedium, color = Shelf.colors.ink, modifier = Modifier.padding(horizontal = 20.dp, vertical = 4.dp))
        val p = plan(shown, nxt, setting, cur.duration)
        PARTS.forEach { (key, part) ->
            val (title, options) = part
            val now = when (key) { "volume" -> p.volume; "eq" -> p.eq; else -> p.filter }
            Text(title, style = MaterialTheme.typography.labelLarge, color = Shelf.colors.ink2, modifier = Modifier.padding(start = 20.dp, top = 8.dp))
            LazyRow(contentPadding = PaddingValues(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                items(options.entries.toList()) { (value, label) ->
                    FilterChip(selected = now == value, label = { Text(label) }, onClick = {
                        onSave(when (key) { "volume" -> choice.copy(volume = value); "eq" -> choice.copy(eq = value); else -> choice.copy(filter = value) }.concrete(cur, nxt))
                    }, colors = FilterChipDefaults.filterChipColors(selectedContainerColor = Shelf.colors.cobalt, selectedLabelColor = Shelf.colors.cobaltInk, labelColor = Shelf.colors.ink))
                }
            }
        }
        val sliders = SliderDefaults.colors(thumbColor = Shelf.colors.cobalt, activeTrackColor = Shelf.colors.cobalt, inactiveTrackColor = Shelf.colors.ink.copy(alpha = .2f))
        if (p.beatmatch) {
            // Length in bars: 1, 2, 4, 8, 16 or 32.
            val steps = listOf(1.0, 2.0, 4.0, 8.0, 16.0, 32.0)
            val at = steps.indexOfFirst { it >= p.beats / 4.0 }.coerceAtLeast(0)
            Text("Length: ${app.shelf.playback.barsLabel(steps[at])}", style = MaterialTheme.typography.labelLarge, color = Shelf.colors.ink2, modifier = Modifier.padding(start = 20.dp, top = 10.dp))
            Row(Modifier.padding(horizontal = 12.dp), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                steps.forEach { b -> TextButton(onClick = { onSave(choice.copy(bars = b).concrete(cur, nxt)) }) { Text(num(b), color = if (b == steps[at]) Shelf.colors.cobalt else Shelf.colors.ink2) } }
            }
            Text("Start: ${shiftLabel(choice.shift ?: 0.0, "bar")}", style = MaterialTheme.typography.labelLarge, color = Shelf.colors.ink2, modifier = Modifier.padding(start = 20.dp, top = 6.dp))
            SaveOnRelease((choice.shift ?: 0.0).toFloat(), -16f..8f, 23, sliders) { v -> onSave(choice.copy(shift = v.roundToInt().toDouble()).concrete(cur, nxt)) }
        } else {
            Text("Length: ${p.length.roundToInt()} seconds", style = MaterialTheme.typography.labelLarge, color = Shelf.colors.ink2, modifier = Modifier.padding(start = 20.dp, top = 10.dp))
            SaveOnRelease((choice.seconds ?: p.length).toFloat(), 1f..30f, 28, sliders) { v -> onSave(choice.copy(seconds = v.roundToInt().toDouble()).concrete(cur, nxt)) }
            Text("Start: ${shiftLabel(choice.shift ?: 0.0, "second")}", style = MaterialTheme.typography.labelLarge, color = Shelf.colors.ink2, modifier = Modifier.padding(start = 20.dp, top = 6.dp))
            SaveOnRelease((choice.shift ?: 0.0).toFloat(), -30f..10f, 39, sliders) { v -> onSave(choice.copy(shift = v.roundToInt().toDouble()).concrete(cur, nxt)) }
        }
        if (choice != TransitionChoice(choice.style)) TextButton(onClick = { onSave(TransitionChoice(choice.style)) }, modifier = Modifier.padding(start = 8.dp)) {
            Text("Reset to ${STYLE_LABEL[choice.style]}", color = Shelf.colors.ink2)
        }
    }
}

/** A slider that saves once, when it's let go (not on every step of the drag). */
@Composable
private fun SaveOnRelease(value: Float, range: ClosedFloatingPointRange<Float>, steps: Int, colors: androidx.compose.material3.SliderColors, onSave: (Float) -> Unit) {
    var dragging by androidx.compose.runtime.remember(value) { androidx.compose.runtime.mutableStateOf(value) }
    Slider(dragging, { dragging = it }, onValueChangeFinished = { if (dragging != value) onSave(dragging) }, valueRange = range, steps = steps,
        colors = colors, modifier = Modifier.padding(horizontal = 20.dp))
}

/** Changing a part of "auto" fixes the style auto picks for this pair, as the web's editor does. */
private fun TransitionChoice.concrete(cur: Track, nxt: Track) = if (style == "auto") copy(style = autoStyle(cur, nxt)) else this

private fun num(x: Double) = if (x % 1.0 == 0.0) x.toLong().toString() else x.toString()

private fun shiftLabel(shift: Double, unit: String) = when {
    shift == 0.0 -> "as planned"
    shift < 0 -> "${num(-shift)} $unit${if (shift != -1.0) "s" else ""} earlier"
    else -> "${num(shift)} $unit${if (shift != 1.0) "s" else ""} later"
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TransitionSheet(cur: Track, nxt: Track, editable: Boolean, onSave: (TransitionChoice) -> Unit, onDismiss: () -> Unit) {
    ModalBottomSheet(onDismissRequest = onDismiss, containerColor = Shelf.colors.sleeve) {
        Column(Modifier.navigationBarsPadding()) { TransitionPicker(cur, nxt, cur.transition, editable, onSave) }
    }
}
