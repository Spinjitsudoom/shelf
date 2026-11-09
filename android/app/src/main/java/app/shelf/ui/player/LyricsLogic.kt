package app.shelf.ui.player

import app.shelf.data.LyricLine

/** The line being sung at [positionS] seconds: the last line that has started (−1 before the first). Lines are in time order. */
fun activeLine(lines: List<LyricLine>, positionS: Double): Int {
    var lo = 0; var hi = lines.size - 1; var found = -1
    while (lo <= hi) {
        val mid = (lo + hi) ushr 1
        if (lines[mid].t <= positionS) { found = mid; lo = mid + 1 } else hi = mid - 1
    }
    return found
}
