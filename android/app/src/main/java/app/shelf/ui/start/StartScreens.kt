package app.shelf.ui.start

import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import app.shelf.R
import app.shelf.ui.theme.Shelf

/** Every start screen: the Shelf mark, a title, then its form, centred and keyboard-aware. */
@Composable
private fun StartFrame(title: String, lead: String, content: @Composable ColumnScope.() -> Unit) {
    Box(Modifier.fillMaxSize().systemBarsPadding().imePadding().verticalScroll(rememberScrollState()), contentAlignment = Alignment.Center) {
        Column(Modifier.widthIn(max = 420.dp).fillMaxWidth().padding(24.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Image(painterResource(R.mipmap.ic_launcher), contentDescription = null, modifier = Modifier.size(64.dp))
            Spacer(Modifier.height(6.dp))
            Text(title, style = MaterialTheme.typography.displayMedium, color = Shelf.colors.ink)
            Text(lead, style = MaterialTheme.typography.bodyLarge, color = Shelf.colors.ink2)
            Spacer(Modifier.height(10.dp))
            content()
        }
    }
}

@Composable
private fun Field(value: String, onChange: (String) -> Unit, label: String, keyboard: KeyboardOptions, onGo: () -> Unit,
                  placeholder: String? = null, password: Boolean = false) {
    var shown by remember { mutableStateOf(false) }
    OutlinedTextField(
        value = value, onValueChange = onChange, label = { Text(label) }, singleLine = true,
        placeholder = placeholder?.let { { Text(it, color = Shelf.colors.ink2) } },
        keyboardOptions = keyboard, keyboardActions = KeyboardActions(onGo = { onGo() }, onDone = { onGo() }),
        visualTransformation = if (password && !shown) PasswordVisualTransformation() else VisualTransformation.None,
        trailingIcon = if (password) { { TextButton(onClick = { shown = !shown }) { Text(if (shown) "Hide" else "Show") } } } else null,
        colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = Shelf.colors.cobalt, focusedLabelColor = Shelf.colors.cobalt,
            unfocusedBorderColor = Shelf.colors.rule, cursorColor = Shelf.colors.cobalt),
        shape = MaterialTheme.shapes.medium,
        modifier = Modifier.fillMaxWidth(),
    )
}

@Composable
private fun Error(text: String?) {
    if (text != null) {
        Text(text, color = Color(0xffff8a80), style = MaterialTheme.typography.bodyMedium,
            modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
    }
}

@Composable
private fun Primary(label: String, busy: Boolean, onClick: () -> Unit) {
    Button(onClick = onClick, enabled = !busy, modifier = Modifier.fillMaxWidth().height(52.dp),
        colors = ButtonDefaults.buttonColors(containerColor = Shelf.colors.cobalt, contentColor = Shelf.colors.cobaltInk,
            disabledContainerColor = Shelf.colors.cobalt.copy(alpha = .6f), disabledContentColor = Shelf.colors.cobaltInk)) {
        if (busy) CircularProgressIndicator(Modifier.size(22.dp), color = Shelf.colors.cobaltInk, strokeWidth = 2.5.dp)
        else Text(label, style = MaterialTheme.typography.labelLarge)
    }
}

@Composable
fun ServerScreen(state: StartViewModel.UiState, onSubmit: (String) -> Unit) {
    var address by rememberSaveable { mutableStateOf(state.address) }
    StartFrame("Shelf", "Connect to the Shelf server with your music.") {
        Field(address, { address = it }, "Server address",
            KeyboardOptions(keyboardType = KeyboardType.Uri, imeAction = ImeAction.Go, autoCorrectEnabled = false), { onSubmit(address) },
            placeholder = "192.168.1.20:4533")
        Text("The address you open Shelf at in a browser.", style = MaterialTheme.typography.bodySmall, color = Shelf.colors.ink2)
        Error(state.error)
        Spacer(Modifier.height(4.dp))
        Primary("Connect", state.busy) { onSubmit(address) }
    }
}

@Composable
fun SignInScreen(state: StartViewModel.UiState, onSignIn: (String, String) -> Unit, onChangeServer: () -> Unit) {
    var user by rememberSaveable { mutableStateOf("") }
    var pass by rememberSaveable { mutableStateOf("") }
    StartFrame("Sign in", "to ${state.address}") {
        state.note?.let { Text(it, style = MaterialTheme.typography.bodyMedium, color = Shelf.colors.cobalt) }
        Field(user, { user = it }, "Username", KeyboardOptions(imeAction = ImeAction.Next, autoCorrectEnabled = false), {})
        Field(pass, { pass = it }, "Password", KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
            { onSignIn(user, pass) }, password = true)
        Error(state.error)
        Spacer(Modifier.height(4.dp))
        Primary("Sign in", state.busy) { onSignIn(user, pass) }
        TextButton(onClick = onChangeServer, modifier = Modifier.align(Alignment.CenterHorizontally)) {
            Text("Change server", color = Shelf.colors.ink2)
        }
    }
}
