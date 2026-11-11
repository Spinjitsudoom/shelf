package app.shelf.playback

/**
 * After a song fails to play: move on to the next, unless several in a row have failed (then
 * stop, so a queue where nothing plays isn't raced through a second at a time).
 */
class ErrorSkip(private val limit: Int = 3) {
    private var inARow = 0

    /** Something played: counting starts again. */
    fun played() { inARow = 0 }

    /** A song failed; true to skip to the next one. */
    fun failed(hasNext: Boolean): Boolean {
        inARow++
        return hasNext && inARow < limit
    }
}

private val QUALITY = Regex("""([?&]q=)([^&#]*)""")

/** The quality a Shelf stream address asks for ("original", "high"…), or null if it isn't one. */
fun qualityIn(uri: String): String? =
    if ("/stream?" in uri) QUALITY.find(uri)?.groupValues?.get(2) else null

/**
 * A streamed song's address, with the quality picked now, as it loads (marked "#pick=<codec>" when
 * queued): a queue made on mobile data then plays the real files once on Wi-Fi. Downloads and
 * other addresses are left as they are.
 */
fun pickQuality(uri: String, quality: (codec: String?) -> String): String {
    val mark = uri.indexOf("#pick=")
    if (mark < 0) return uri
    val codec = uri.substring(mark + 6).ifEmpty { null }
    return QUALITY.replace(uri.substring(0, mark)) { it.groupValues[1] + quality(codec) }
}
