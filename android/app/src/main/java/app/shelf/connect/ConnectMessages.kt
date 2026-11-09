package app.shelf.connect

import app.shelf.data.Track
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/*
 * Shelf Connect's messages, as the server (src/shelf/connect.py) and the web app (connect.js)
 * send them. Songs travel as the API's track objects; anything the phone doesn't know is skipped.
 */

internal val connectJson = Json { ignoreUnknownKeys = true; coerceInputValues = true; explicitNulls = false; encodeDefaults = true }

@Serializable data class DeviceInfo(val id: String, val name: String = "", val kind: String = "computer")

/** Where the music was started from: a label and the web app's link to it. */
@Serializable data class WebContext(val label: String = "", val href: String? = null)

/** What the playing device reports. Times are in seconds. */
data class RemoteState(
    val index: Int = 0, val track: Track? = null, val playing: Boolean = false, val position: Double = 0.0, val duration: Double = 0.0,
    val shuffle: Boolean = false, val repeat: String = "off", val context: WebContext? = null, val volume: Double = 1.0,
)

/** Everything needed to carry on playing on another device. */
data class Snapshot(
    val queue: List<Track>, val index: Int, val position: Double, val playing: Boolean,
    val shuffle: Boolean = false, val repeat: String = "off", val context: WebContext? = null,
)

sealed interface Incoming {
    data class Welcome(val you: String, val devices: List<DeviceInfo>, val active: String?, val state: RemoteState?, val queue: List<Track>?) : Incoming
    data class Devices(val devices: List<DeviceInfo>, val active: String?) : Incoming
    data class State(val state: RemoteState, val queue: List<Track>?) : Incoming
    data class Cmd(val name: String, val args: JsonArray) : Incoming
    data class Takeover(val snapshot: Snapshot) : Incoming
    data object Release : Incoming
    data object Duplicate : Incoming
    data class Notice(val text: String) : Incoming
}

private fun JsonObject.str(k: String) = (this[k] as? JsonPrimitive)?.contentOrNull
private fun JsonObject.num(k: String) = (this[k] as? JsonPrimitive)?.doubleOrNull
private fun JsonObject.obj(k: String) = this[k] as? JsonObject

private fun tracks(e: JsonElement?): List<Track> = (e as? JsonArray)?.mapNotNull { t ->
    runCatching { connectJson.decodeFromJsonElement(Track.serializer(), t) }.getOrNull()
}.orEmpty()

private fun track(e: JsonElement?): Track? = (e as? JsonObject)?.let { runCatching { connectJson.decodeFromJsonElement(Track.serializer(), it) }.getOrNull() }

/** Shuffle is true, false, or "smart" (which is on too). */
private fun shuffleOf(e: JsonElement?): Boolean = (e as? JsonPrimitive)?.let { it.booleanOrNull ?: (it.contentOrNull == "smart") } ?: false

private fun contextOf(e: JsonElement?): WebContext? = (e as? JsonObject)?.let { WebContext(it.str("label") ?: "", it.str("href")) }

private fun devices(e: JsonElement?): List<DeviceInfo> = (e as? JsonArray)?.mapNotNull { d ->
    runCatching { connectJson.decodeFromJsonElement(DeviceInfo.serializer(), d) }.getOrNull()
}.orEmpty()

fun remoteState(o: JsonObject) = RemoteState(
    index = o.num("index")?.toInt() ?: 0, track = track(o["track"]), playing = (o["playing"] as? JsonPrimitive)?.booleanOrNull ?: false,
    position = o.num("position") ?: 0.0, duration = o.num("duration") ?: 0.0, shuffle = shuffleOf(o["shuffle"]),
    repeat = o.str("repeat")?.takeIf { it in setOf("off", "all", "one") } ?: "off", context = contextOf(o["context"]), volume = o.num("volume") ?: 1.0,
)

fun snapshot(o: JsonObject) = Snapshot(
    queue = tracks(o["queue"]), index = o.num("index")?.toInt() ?: 0, position = o.num("position") ?: 0.0,
    playing = (o["playing"] as? JsonPrimitive)?.booleanOrNull ?: false, shuffle = shuffleOf(o["shuffle"]),
    repeat = o.str("repeat") ?: "off", context = contextOf(o["context"]),
)

/** A message from the server, or null for one this version doesn't know (or isn't JSON). */
fun parseIncoming(text: String): Incoming? {
    val o = runCatching { connectJson.parseToJsonElement(text).jsonObject }.getOrNull() ?: return null
    val queue = { o.obj("queue")?.let { tracks(it["tracks"]) } }
    return when (o.str("type")) {
        "welcome" -> Incoming.Welcome(o.str("you") ?: "", devices(o["devices"]), o.str("active"), o.obj("state")?.let(::remoteState), queue())
        "devices" -> Incoming.Devices(devices(o["devices"]), o.str("active"))
        "state" -> o.obj("state")?.let { Incoming.State(remoteState(it), queue()) }
        "cmd" -> o.str("name")?.let { Incoming.Cmd(it, (o["args"] as? JsonArray) ?: JsonArray(emptyList())) }
        "takeover" -> o.obj("snapshot")?.let { Incoming.Takeover(snapshot(it)) }
        "release" -> Incoming.Release
        "duplicate" -> Incoming.Duplicate
        "notice" -> Incoming.Notice(o.str("text") ?: "")
        else -> null
    }
}

fun tracksJson(list: List<Track>): JsonElement = connectJson.encodeToJsonElement(ListSerializer(Track.serializer()), list)
fun contextJson(c: WebContext?): JsonElement = c?.let { connectJson.encodeToJsonElement(WebContext.serializer(), it) } ?: JsonNull

fun snapshotJson(s: Snapshot): JsonObject = JsonObject(mapOf(
    "queue" to tracksJson(s.queue), "original" to JsonNull, "index" to JsonPrimitive(s.index), "position" to JsonPrimitive(s.position),
    "playing" to JsonPrimitive(s.playing), "shuffle" to JsonPrimitive(s.shuffle), "repeat" to JsonPrimitive(s.repeat), "context" to contextJson(s.context),
))

/** The web app's link for one of the app's pages ("album/5" → "#/album/5"; Favourites is "#/liked" there). */
fun webHref(route: String): String = if (route == "favourites") "#/liked" else "#/$route"

/** The app's page for a web link, or null when there isn't one. */
fun nativeRoute(href: String?): String? {
    val path = href?.removePrefix("#/")?.substringBefore('?')?.takeIf { it.isNotBlank() && href.startsWith("#/") } ?: return null
    return if (path == "liked") "favourites" else path
}
