package app.shelf.playback

import android.media.MediaCodecList
import java.util.concurrent.ConcurrentHashMap

/** Which audio formats this phone has a decoder for (asked once per format, then remembered). */
object Decoders {
    private val known = ConcurrentHashMap<String, Boolean>()
    private val decoders by lazy { MediaCodecList(MediaCodecList.REGULAR_CODECS).codecInfos.filter { !it.isEncoder } }

    fun has(mime: String): Boolean = known.getOrPut(mime) {
        runCatching { decoders.any { info -> info.supportedTypes.any { it.equals(mime, ignoreCase = true) } } }.getOrDefault(true)
    }
}
