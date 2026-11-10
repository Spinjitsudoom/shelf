package app.shelf.ui.settings

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.shelf.AppContainer
import app.shelf.R
import app.shelf.playback.Eq
import app.shelf.ui.theme.Shelf
import kotlin.math.abs
import kotlin.math.roundToInt

/** The equalizer (the web app's six bands and presets), balance and mono, for this phone. */
@Composable
fun EqualizerScreen(container: AppContainer, onBack: () -> Unit) {
    val s by container.settings.settings.collectAsStateWithLifecycle()
    val sliders = SliderDefaults.colors(thumbColor = Shelf.colors.cobalt, activeTrackColor = Shelf.colors.cobalt, inactiveTrackColor = Shelf.colors.ink.copy(alpha = .2f))
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 32.dp)) {
        item {
            Row(Modifier.statusBarsPadding().padding(4.dp), verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = onBack) { Icon(painterResource(R.drawable.ic_back), "Back", tint = Shelf.colors.ink) }
                Text("Equalizer", style = MaterialTheme.typography.headlineSmall, color = Shelf.colors.ink, modifier = Modifier.weight(1f))
                Switch(s.eqEnabled, { on -> container.settings.update { it.copy(eqEnabled = on) } }, modifier = Modifier.padding(end = 16.dp),
                    colors = SwitchDefaults.colors(checkedTrackColor = Shelf.colors.cobalt, checkedThumbColor = Shelf.colors.cobaltInk))
            }
        }
        item {
            LazyRow(contentPadding = PaddingValues(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                items(Eq.PRESETS.keys.toList()) { name ->
                    FilterChip(selected = s.eqPreset == name, label = { Text(name) },
                        onClick = { container.settings.update { it.copy(eqEnabled = true, eqPreset = name, eqGains = Eq.PRESETS.getValue(name)) } },
                        colors = FilterChipDefaults.filterChipColors(selectedContainerColor = Shelf.colors.cobalt, selectedLabelColor = Shelf.colors.cobaltInk, labelColor = Shelf.colors.ink))
                }
            }
        }
        items(Eq.BANDS.indices.toList()) { i ->
            val g = s.eqGains.getOrElse(i) { 0.0 }
            Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("${Eq.LABELS[i]} Hz", style = MaterialTheme.typography.labelLarge, color = Shelf.colors.ink2, modifier = Modifier.width(64.dp))
                Slider(g.toFloat(), { v ->
                    // Half-dB steps; moving a band makes it your own setting.
                    val gains = s.eqGains.toMutableList().apply { this[i] = (v * 2).roundToInt() / 2.0 }
                    container.settings.update { it.copy(eqEnabled = true, eqGains = gains, eqPreset = Eq.PRESETS.entries.firstOrNull { e -> e.value == gains }?.key ?: "Custom") }
                }, valueRange = -12f..12f, colors = sliders, modifier = Modifier.weight(1f), enabled = s.eqEnabled)
                Text((if (g > 0) "+" else "") + (if (g % 1.0 == 0.0) g.toInt().toString() else g.toString()) + " dB",
                    style = MaterialTheme.typography.labelMedium, color = Shelf.colors.ink2, modifier = Modifier.width(60.dp).padding(start = 8.dp))
            }
        }
        item {
            Column(Modifier.padding(horizontal = 20.dp, vertical = 16.dp)) {
                Text("Balance", style = MaterialTheme.typography.titleMedium, color = Shelf.colors.ink)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("L", color = Shelf.colors.ink2)
                    Slider(s.balance, { v -> container.settings.update { it.copy(balance = if (abs(v) < 0.06f) 0f else v) } }, valueRange = -1f..1f,
                        colors = sliders, modifier = Modifier.weight(1f).padding(horizontal = 8.dp))
                    Text("R", color = Shelf.colors.ink2)
                }
                Text(when { s.balance == 0f -> "Centre"; s.balance < 0 -> "${(-s.balance * 100).roundToInt()}% left"; else -> "${(s.balance * 100).roundToInt()}% right" },
                    style = MaterialTheme.typography.bodySmall, color = Shelf.colors.ink2, modifier = Modifier.clickable { container.settings.update { it.copy(balance = 0f) } })
            }
            Row(Modifier.fillMaxWidth().clickable { container.settings.update { it.copy(mono = !s.mono) } }.padding(horizontal = 20.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Mono", style = MaterialTheme.typography.titleMedium, color = Shelf.colors.ink)
                    Text("Both ears hear the same, for one earbud", style = MaterialTheme.typography.bodySmall, color = Shelf.colors.ink2)
                }
                Switch(s.mono, { on -> container.settings.update { it.copy(mono = on) } },
                    colors = SwitchDefaults.colors(checkedTrackColor = Shelf.colors.cobalt, checkedThumbColor = Shelf.colors.cobaltInk))
            }
        }
    }
}
