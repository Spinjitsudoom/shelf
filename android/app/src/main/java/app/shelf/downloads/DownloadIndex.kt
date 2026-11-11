package app.shelf.downloads

import androidx.media3.exoplayer.offline.Download
import app.shelf.data.CoverRef
import app.shelf.data.Track
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import java.io.File

/** Something downloaded as a whole: an album, a playlist, or Favourites (id 0), with what's needed to show and play it offline. */
@Serializable
data class Downloadable(
    val kind: String, val id: Int, val name: String, val subtitle: String = "", val color: String? = null,
    val covers: List<CoverRef> = emptyList(), val tracks: List<Track> = emptyList(),
) {
    val key get() = "$kind:$id"
}

private val json = Json { ignoreUnknownKeys = true; encodeDefaults = true }

/** What's been downloaded, kept in a small JSON file (the songs themselves are in Media3's download cache). */
class DownloadIndex(private val file: File) {
    private var items: List<Downloadable> = runCatching { json.decodeFromString(ListSerializer(Downloadable.serializer()), file.readText()) }.getOrDefault(emptyList())

    @Synchronized fun all(): List<Downloadable> = items
    @Synchronized fun get(kind: String, id: Int): Downloadable? = items.firstOrNull { it.kind == kind && it.id == id }
    fun isDownloaded(kind: String, id: Int) = get(kind, id) != null

    /** Add a collection, or replace it if it's there already (a playlist that changed). */
    @Synchronized fun add(item: Downloadable) {
        val i = items.indexOfFirst { it.key == item.key }
        items = if (i < 0) items + item else items.toMutableList().apply { set(i, item) }
        save()
    }

    @Synchronized fun remove(kind: String, id: Int) { items = items.filterNot { it.kind == kind && it.id == id }; save() }

    /** The songs no other downloaded collection has: the ones to delete when this one goes. */
    @Synchronized fun tracksOnlyIn(kind: String, id: Int): Set<Int> {
        val mine = get(kind, id)?.tracks?.map { it.id }?.toSet() ?: return emptySet()
        val others = items.filterNot { it.kind == kind && it.id == id }.flatMap { c -> c.tracks.map { it.id } }.toSet()
        return mine - others
    }

    /** Every downloaded song (to find the one to play from). */
    @Synchronized fun trackIds(): Set<Int> = items.flatMap { c -> c.tracks.map { it.id } }.toSet()

    private fun save() {
        file.parentFile?.mkdirs()
        val tmp = File(file.path + ".tmp")
        tmp.writeText(json.encodeToString(ListSerializer(Downloadable.serializer()), items))
        tmp.renameTo(file)
    }
}

/** Downloaded only when every song has finished (a failed or unfinished song means it isn't). */
fun isComplete(item: Downloadable, states: Map<Int, Int>): Boolean = item.tracks.all { states[it.id] == Download.STATE_COMPLETED }

/** How far along a collection is, 0..1: finished songs count whole, songs downloading count their percentage, failed ones nothing. */
fun progressOf(item: Downloadable, states: Map<Int, Int>, percents: Map<Int, Float>): Float {
    if (item.tracks.isEmpty()) return 1f
    val sum = item.tracks.sumOf { t ->
        when (states[t.id]) {
            Download.STATE_COMPLETED -> 1.0
            Download.STATE_DOWNLOADING, Download.STATE_QUEUED, Download.STATE_RESTARTING -> ((percents[t.id] ?: 0f).coerceIn(0f, 100f) / 100.0)
            else -> 0.0
        }
    }
    return (sum / item.tracks.size).toFloat()
}

/**
 * Whether a downloaded collection needs fetching again: its songs or name changed on the server,
 * or a song's download failed or went missing. Not while songs are still on their way.
 */
fun needsFetch(old: Downloadable?, new: Downloadable, states: Map<Int, Int>): Boolean {
    if (old == null) return false
    if (old.tracks.map { it.id } != new.tracks.map { it.id } || old.name != new.name) return true
    return new.tracks.any { states[it.id] == null || states[it.id] == Download.STATE_FAILED }
}

/**
 * Downloaded songs (id to the address they were fetched from) saved in another quality than
 * [wanted] now, to fetch again. Addresses that aren't Shelf streams are left alone.
 */
fun toRefetch(done: Map<Int, String>, wanted: (Int) -> String): Set<Int> =
    done.filter { (id, uri) -> Regex("""/stream\?(?:.*&)?q=([^&]+)""").find(uri)?.groupValues?.get(1)?.let { it != wanted(id) } == true }.keys
