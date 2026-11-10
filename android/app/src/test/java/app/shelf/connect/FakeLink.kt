package app.shelf.connect

import app.shelf.data.Track
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject

fun tr(id: Int) = Track(id = id, title = "Song $id", artist = "Band", album = "Album", albumId = 5, duration = 200.0)

/** Connect without a server: what was sent, and a state the test sets. */
class FakeLink(ui: ConnectUi) : RemoteLink {
    override val ui = MutableStateFlow(ui)
    val cmds = mutableListOf<Pair<String, List<JsonElement>>>()
    val sent = mutableListOf<JsonObject>()
    override fun cmd(name: String, vararg args: JsonElement) { cmds += name to args.toList() }
    override fun send(msg: JsonObject) { sent += msg }
    override fun optimistic(change: (RemoteState) -> RemoteState) = ui.update { u -> u.state?.let { u.copy(state = change(it)) } ?: u }
    override fun optimisticQueue(change: (List<Track>) -> List<Track>) = ui.update { u -> u.copy(queue = change(u.queue)) }
}

fun remoteUi(now: Long = 0) = ConnectUi(
    connected = true, selfId = "me", devices = listOf(DeviceInfo("pc", "Desk"), DeviceInfo("me", "Redmi", "phone")), activeId = "pc",
    state = RemoteState(index = 1, playing = true, position = 30.0, duration = 200.0, shuffle = true, repeat = "all", volume = 0.5),
    queue = listOf(tr(1), tr(2), tr(3)), at = now,
)
