package app.shelf.ui.settings

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import kotlinx.coroutines.launch
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.runtime.produceState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.shelf.AppContainer
import app.shelf.R
import app.shelf.settings.Settings
import app.shelf.ui.theme.Shelf

private val QUALITIES = listOf("original" to "Original", "veryhigh" to "320 kbps", "high" to "192 kbps", "normal" to "128 kbps", "low" to "96 kbps")

@Composable
fun SettingsScreen(container: AppContainer, appVersion: String, onChangeServer: () -> Unit, onSignOut: () -> Unit, onBack: () -> Unit,
                   onAdmin: () -> Unit = {}, onEqualizer: () -> Unit = {}) {
    val admin by produceState(false, container.store.server) { value = runCatching { container.api?.session()?.user?.admin == true }.getOrDefault(false) }
    val s by container.settings.settings.collectAsStateWithLifecycle()
    val serverVersion by produceState("", container.store.server) { value = runCatching { container.api?.ping() ?: "" }.getOrDefault("") }
    fun set(t: (Settings) -> Settings) = container.settings.update(t)
    LazyColumn(Modifier.fillMaxSize()) {
        item {
            Row(Modifier.statusBarsPadding().padding(start = 4.dp, top = 6.dp, end = 16.dp), verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = onBack) { Icon(painterResource(R.drawable.ic_back), "Back", tint = Shelf.colors.ink) }
                Text("Settings", style = MaterialTheme.typography.displaySmall, color = Shelf.colors.ink)
            }
        }
        item { Section("Listening") }
        item { Choice("Quality on Wi-Fi", "Original sends your files as they are.", s.wifiQuality, QUALITIES) { v -> set { it.copy(wifiQuality = v) } } }
        item {
            Choice("Quality on mobile data", "Original sends your files as they are. Automatic makes lossless files smaller to save data.", s.dataQuality,
                QUALITIES.take(1) + ("auto" to "Automatic") + QUALITIES.drop(1)) { v -> set { it.copy(dataQuality = v) } }
        }
        item { Toggle("Autoplay", "When the music runs out, carry on with similar songs.", s.autoplay) { v -> set { it.copy(autoplay = v) } } }
        item {
            Choice("Crossfade", "Songs fade into each other. Playlists with Mix on blend in their own way.", s.crossfade.toString(),
                listOf("0" to "Off") + listOf(2, 4, 6, 8, 10, 12).map { "$it" to "$it s" }) { v -> set { it.copy(crossfade = v.toInt()) } }
        }
        if (s.crossfade > 0) item {
            Toggle("Crossfade albums too", "Off keeps albums played in order seamless, as they were made.", s.crossfadeAlbums) { v -> set { it.copy(crossfadeAlbums = v) } }
        }
        item { Toggle("Even out volume", "Songs play at the same loudness, as on the web.", s.normalize) { v -> set { it.copy(normalize = v) } } }
        if (s.normalize) item {
            Segmented("Loudness", s.loudness, listOf("quiet" to "Quiet", "normal" to "Normal", "loud" to "Loud")) { v -> set { it.copy(loudness = v) } }
        }
        item {
            Row(Modifier.fillMaxWidth().clickable(onClick = onEqualizer).padding(horizontal = 20.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Equalizer", style = MaterialTheme.typography.titleMedium, color = Shelf.colors.ink)
                    Text(if (s.eqEnabled) s.eqPreset else "Off", style = MaterialTheme.typography.bodySmall, color = Shelf.colors.ink2)
                }
            }
        }
        item { Section("Appearance") }
        item { Segmented("Theme", s.theme, listOf("dark" to "Dark", "light" to "Light", "system" to "Phone")) { v -> set { it.copy(theme = v) } } }
        item { Segmented("Shelf", s.format, listOf("cd" to "CDs", "vinyl" to "Vinyl")) { v -> set { it.copy(format = v) } } }
        item { Toggle("Spin the disc", "The CD or record turns on Now Playing while the music plays.", s.spinDisc) { v -> set { it.copy(spinDisc = v) } } }
        item { Section("Downloads") }
        item { Choice("Download quality", "For albums and playlists you download. Original keeps your files as they are.", s.downloadQuality, QUALITIES) { v -> set { it.copy(downloadQuality = v) } } }
        item { Section("Devices and privacy") }
        item { DeviceName(s.deviceName) { v -> set { it.copy(deviceName = v) } } }
        item { Toggle("Private session", "While it's on, what you play on this phone doesn't show in friend activity.", s.privateSession) { v -> set { it.copy(privateSession = v) } } }
        item { ShareActivity(container) }
        item { Section("Account") }
        item {
            Column(Modifier.padding(horizontal = 20.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("Signed in as ${container.store.username ?: "—"} on ${container.store.server?.replaceFirst(Regex("^https?://"), "") ?: "—"}",
                    style = MaterialTheme.typography.bodyMedium, color = Shelf.colors.ink2)
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    OutlinedButton(onClick = onChangeServer) { Text("Change server", color = Shelf.colors.ink) }
                    OutlinedButton(onClick = onSignOut) { Text("Sign out", color = Shelf.colors.ink) }
                }
                // Admins: users, adding music, CD ripping and server updates, from the web app.
                if (admin) OutlinedButton(onClick = onAdmin) { Text("Admin dashboard", color = Shelf.colors.ink) }
            }
        }
        item { Section("About") }
        item {
            Text("Shelf for Android $appVersion" + if (serverVersion.isNotEmpty()) ", server $serverVersion" else "",
                style = MaterialTheme.typography.bodyMedium, color = Shelf.colors.ink2, modifier = Modifier.padding(horizontal = 20.dp, vertical = 8.dp))
            UpdateCheck(container)
            Spacer(Modifier.height(32.dp))
        }
    }
}

@Composable
private fun Section(title: String) {
    Column(Modifier.padding(top = 18.dp)) {
        HorizontalDivider(color = Shelf.colors.rule)
        Text(title, style = MaterialTheme.typography.titleLarge, color = Shelf.colors.ink, modifier = Modifier.padding(start = 20.dp, top = 16.dp, bottom = 4.dp))
    }
}

@Composable
private fun Toggle(title: String, hint: String, on: Boolean, onChange: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth().clickable { onChange(!on) }.padding(horizontal = 20.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.titleMedium, color = Shelf.colors.ink)
            Text(hint, style = MaterialTheme.typography.bodySmall, color = Shelf.colors.ink2)
        }
        Switch(on, onChange, colors = SwitchDefaults.colors(checkedTrackColor = Shelf.colors.cobalt, checkedThumbColor = Shelf.colors.cobaltInk))
    }
}

@Composable
private fun Segmented(title: String, value: String, options: List<Pair<String, String>>, onChange: (String) -> Unit) {
    Column(Modifier.padding(horizontal = 20.dp, vertical = 10.dp)) {
        Text(title, style = MaterialTheme.typography.titleMedium, color = Shelf.colors.ink, modifier = Modifier.padding(bottom = 8.dp))
        SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
            options.forEachIndexed { i, (key, label) ->
                SegmentedButton(selected = value == key, onClick = { onChange(key) }, shape = SegmentedButtonDefaults.itemShape(i, options.size),
                    colors = SegmentedButtonDefaults.colors(activeContainerColor = Shelf.colors.cobalt, activeContentColor = Shelf.colors.cobaltInk,
                        inactiveContainerColor = Shelf.colors.tray, inactiveContentColor = Shelf.colors.ink)) { Text(label) }
            }
        }
    }
}

@Composable
private fun Choice(title: String, hint: String, value: String, options: List<Pair<String, String>>, onChange: (String) -> Unit) {
    Column(Modifier.padding(horizontal = 20.dp, vertical = 10.dp)) {
        Text(title, style = MaterialTheme.typography.titleMedium, color = Shelf.colors.ink)
        Text(hint, style = MaterialTheme.typography.bodySmall, color = Shelf.colors.ink2)
        Spacer(Modifier.height(8.dp))
        androidx.compose.foundation.layout.FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            options.forEach { (key, label) ->
                androidx.compose.material3.FilterChip(selected = value == key, onClick = { onChange(key) }, label = { Text(label) },
                    colors = androidx.compose.material3.FilterChipDefaults.filterChipColors(selectedContainerColor = Shelf.colors.cobalt,
                        selectedLabelColor = Shelf.colors.cobaltInk, labelColor = Shelf.colors.ink))
            }
        }
    }
}

/** "Check for updates": asks GitHub now, and offers to install a newer Shelf. */
@Composable
private fun UpdateCheck(container: app.shelf.AppContainer) {
    val context = androidx.compose.ui.platform.LocalContext.current
    if (!app.shelf.update.Updater.enabled(context)) return
    val scope = androidx.compose.runtime.rememberCoroutineScope()
    var busy by androidx.compose.runtime.remember { androidx.compose.runtime.mutableStateOf(false) }
    var result by androidx.compose.runtime.remember { androidx.compose.runtime.mutableStateOf<app.shelf.update.UpdateResult?>(null) }
    Row(Modifier.padding(horizontal = 20.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        when (val r = result) {
            is app.shelf.update.UpdateResult.Ready -> androidx.compose.material3.Button(onClick = {
                context.startActivity(android.content.Intent(context, app.shelf.update.UpdateActivity::class.java).setAction(app.shelf.update.UpdateActivity.ACTION_INSTALL))
            }) { Text("Install Shelf ${r.version}") }
            else -> OutlinedButton(enabled = !busy, onClick = {
                busy = true
                scope.launch { result = app.shelf.update.Updater(context.applicationContext, container.plainHttp).check(force = true); busy = false }
            }) { Text(if (busy) "Checking…" else "Check for updates", color = Shelf.colors.ink) }
        }
        when (val r = result) {
            app.shelf.update.UpdateResult.UpToDate -> Text("You have the latest version.", style = MaterialTheme.typography.bodySmall, color = Shelf.colors.ink2)
            is app.shelf.update.UpdateResult.Failed -> Text(r.message, style = MaterialTheme.typography.bodySmall, color = Shelf.colors.ink2)
            else -> {}
        }
    }
}

/** This phone's name in your other devices' lists (empty: the phone's own name). */
@Composable
private fun DeviceName(value: String, onChange: (String) -> Unit) {
    var text by androidx.compose.runtime.saveable.rememberSaveable(value) { androidx.compose.runtime.mutableStateOf(value) }
    Column(Modifier.padding(horizontal = 20.dp, vertical = 10.dp)) {
        Text("This phone's name", style = MaterialTheme.typography.titleMedium, color = Shelf.colors.ink)
        Text("How it shows up when you pick where the music plays.", style = MaterialTheme.typography.bodySmall, color = Shelf.colors.ink2)
        androidx.compose.material3.OutlinedTextField(text, { text = it.take(60) }, singleLine = true, placeholder = { Text("The phone's own name") },
            modifier = Modifier.fillMaxWidth().padding(top = 6.dp).onFocusChanged { if (!it.isFocused && text != value) onChange(text.trim()) },
            keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(imeAction = androidx.compose.ui.text.input.ImeAction.Done),
            keyboardActions = androidx.compose.foundation.text.KeyboardActions(onDone = { onChange(text.trim()) }))
    }
}

/** Whether people on this server see what you play (friend activity, and Blends with you). Kept on the server, for all your devices. */
@Composable
private fun ShareActivity(container: AppContainer) {
    val scope = androidx.compose.runtime.rememberCoroutineScope()
    var on by androidx.compose.runtime.remember { androidx.compose.runtime.mutableStateOf<Boolean?>(null) }
    androidx.compose.runtime.LaunchedEffect(Unit) { on = runCatching { container.api?.session()?.user?.shareActivity }.getOrNull() }
    val value = on ?: return
    Toggle("Share what I play", "People on this server see it in friend activity, and can make a Blend with you.", value) { v ->
        on = v
        scope.launch { if (runCatching { container.api?.setShareActivity(v) }.isFailure) on = !v }
    }
}
