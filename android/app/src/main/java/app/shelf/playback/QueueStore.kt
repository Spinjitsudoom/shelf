package app.shelf.playback

import app.shelf.data.Track
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.io.File

/** What's queued and where, saved so the music picks up where it was after the app is killed. */
@Serializable
data class QueueSnapshot(
    val tracks: List<Track>,
    val index: Int,
    val positionMs: Long,
    val context: PlayContext? = null,
    val shuffle: Boolean = false,
    val repeat: Int = 0, // Player.REPEAT_MODE_*: 0 off, 1 one, 2 all
)

class QueueStore(private val file: File) {
    private val json = Json { ignoreUnknownKeys = true }

    fun save(snapshot: QueueSnapshot) {
        val tmp = File(file.parentFile, file.name + ".tmp")
        tmp.writeText(json.encodeToString(QueueSnapshot.serializer(), snapshot))
        tmp.renameTo(file) // whole or not at all
    }

    fun load(): QueueSnapshot? = try {
        if (file.exists()) json.decodeFromString(QueueSnapshot.serializer(), file.readText()) else null
    } catch (e: Exception) {
        null
    }
}
