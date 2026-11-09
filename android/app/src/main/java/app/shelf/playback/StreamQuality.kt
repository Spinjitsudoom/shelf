package app.shelf.playback

private val LOSSLESS = setOf("flac", "alac", "pcm", "wav", "wavpack", "ape", "aiff")

/**
 * Which version of a song to stream: the file itself on Wi-Fi; on mobile data a 192 kbps copy,
 * but only of big lossless files. An MP3 or AAC is small already, and converting it first
 * would only make it slow to start.
 */
fun streamQuality(codec: String?, metered: Boolean): String = when {
    !metered -> "original"
    codec == null || codec.lowercase() in LOSSLESS -> "high"
    else -> "original"
}
