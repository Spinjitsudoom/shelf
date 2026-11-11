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

/** Lossless formats a phone may lack a decoder for (FLAC before Android 8.1; ALAC on some phones). */
private val DECODER_MIMES = mapOf("flac" to "audio/flac", "alac" to "audio/alac")

/**
 * The quality to ask for, given what this phone can play: a lossless file it has no decoder for
 * comes as a 320 kbps copy instead of as it is (the server makes one). Everything else as chosen.
 */
fun playableQuality(codec: String?, quality: String, canDecode: (String) -> Boolean): String {
    val mime = DECODER_MIMES[codec?.lowercase()] ?: return quality
    return if (quality == "original" && !canDecode(mime)) "veryhigh" else quality
}
