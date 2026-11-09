package app.shelf.ui.theme

import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color

/** Shelf's colours, the same as the web app's (style.css): a CD tray, its sleeve, and cobalt. */
@Immutable
data class ShelfColors(
    val tray: Color,     // page background
    val sleeve: Color,   // raised surfaces
    val ink: Color,
    val ink2: Color,     // secondary text
    val rule: Color,
    val cobalt: Color,   // accent
    val cobaltInk: Color, // text on cobalt
    val dark: Boolean,
) {
    companion object {
        val Dark = ShelfColors(
            tray = Color(0xff1a1d24), sleeve = Color(0xff232731), ink = Color(0xffe6e9ef), ink2 = Color(0xff99a1b0),
            rule = Color(0xff323745), cobalt = Color(0xff8199ff), cobaltInk = Color(0xff0f1424), dark = true,
        )
        val Light = ShelfColors(
            tray = Color(0xffe9ebee), sleeve = Color(0xfff7f8fa), ink = Color(0xff1c2029), ink2 = Color(0xff5a6271),
            rule = Color(0xffd3d7de), cobalt = Color(0xff2c4fd0), cobaltInk = Color(0xffffffff), dark = false,
        )
    }
}

val LocalShelfColors = staticCompositionLocalOf { ShelfColors.Dark }
