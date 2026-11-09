package app.shelf.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider

/** Shelf's look: its own colours and type on Material 3's components. Dark unless asked otherwise. */
@Composable
fun ShelfTheme(dark: Boolean = true, content: @Composable () -> Unit) {
    val c = if (dark) ShelfColors.Dark else ShelfColors.Light
    val scheme = (if (dark) darkColorScheme() else lightColorScheme()).copy(
        primary = c.cobalt, onPrimary = c.cobaltInk,
        background = c.tray, onBackground = c.ink,
        surface = c.tray, onSurface = c.ink, onSurfaceVariant = c.ink2,
        surfaceContainer = c.sleeve, surfaceContainerHigh = c.sleeve, surfaceContainerLow = c.sleeve,
        surfaceContainerHighest = c.sleeve, surfaceContainerLowest = c.tray, surfaceVariant = c.sleeve,
        outline = c.rule, outlineVariant = c.rule,
    )
    CompositionLocalProvider(LocalShelfColors provides c) {
        MaterialTheme(colorScheme = scheme, typography = ShelfType, content = content)
    }
}

/** Shelf's colour tokens inside a ShelfTheme. */
object Shelf {
    val colors: ShelfColors @Composable get() = LocalShelfColors.current
}
