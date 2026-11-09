package app.shelf.ui.covers

import androidx.compose.ui.graphics.Color

/** An album's colour from the server ("#rrggbb"), or a steady colour made from its title. */
fun albumColor(hex: String?, title: String): Color {
    if (hex != null && Regex("^#[0-9a-fA-F]{6}$").matches(hex)) {
        return Color(0xff000000 or hex.substring(1).toLong(16))
    }
    return fallbackColor(title)
}

/** The same colour the web app picks for a title (util.js fallbackColor): hsl(hash % 360, 28%, 42%). */
fun fallbackColor(text: String): Color {
    var h = 0L
    var i = 0
    while (i < text.length) {
        val cp = text.codePointAt(i)
        h = (h * 31 + cp) and 0xffffffffL
        i += Character.charCount(cp)
    }
    return Color.hsl((h % 360).toFloat(), 0.28f, 0.42f)
}
