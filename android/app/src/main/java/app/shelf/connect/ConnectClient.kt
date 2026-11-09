package app.shelf.connect

import android.os.Handler
import android.os.Looper
import app.shelf.data.Track
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import java.util.concurrent.TimeUnit
import kotlin.math.min

/** What Connect knows: the devices, which one is playing, and what it reported. */
data class ConnectUi(
    val connected: Boolean = false, val selfId: String = "", val devices: List<DeviceInfo> = emptyList(), val activeId: String? = null,
    val state: RemoteState? = null, val queue: List<Track> = emptyList(), val at: Long = 0,
) {
    /** Another device is playing, so this phone's controls drive it. */
    val remote get() = activeId != null && activeId != selfId && devices.any { it.id == activeId }
    val activeDevice get() = devices.firstOrNull { it.id == activeId }
}

/** What the player side hears from Connect (on the main thread). */
interface ConnectListener {
    fun onConnected() {}
    fun onCmd(name: String, args: JsonArray) {}
    fun onTakeover(snapshot: Snapshot) {}
    fun onRelease() {}
    fun onNotice(text: String) {}
}

private val main by lazy { Handler(Looper.getMainLooper()) }

/**
 * Shelf Connect: a WebSocket to the server's device hub, so this phone can play for the others
 * or control the one that's playing. It reconnects by itself (1, 2, 4… up to 30 s apart), and
 * controls pressed while it's down are sent when it's back if they're under a minute old.
 */
class ConnectClient(
    private val identity: DeviceIdentity,
    okHttp: OkHttpClient,
    private val server: () -> String?,
    private val clock: () -> Long = System::currentTimeMillis,
    private val post: (Runnable) -> Unit = { main.post(it) },
    private val schedule: (Long, () -> Unit) -> Unit = { delay, run -> main.postDelayed(run, delay) },
) {
    private val http = okHttp.newBuilder().readTimeout(0, TimeUnit.MILLISECONDS).pingInterval(20, TimeUnit.SECONDS).build()
    private val _ui = MutableStateFlow(ConnectUi(selfId = identity.id))
    val ui: StateFlow<ConnectUi> = _ui
    var listener: ConnectListener? = null

    private var started = false
    private var socket: WebSocket? = null
    private var generation = 0
    private var retry = 0
    private val held = ArrayDeque<Pair<Long, JsonObject>>()

    fun start() { post { if (!started) { started = true; connect() } } }

    fun stop() {
        started = false
        generation++
        socket?.close(1000, null)
        socket = null
        _ui.update { it.copy(connected = false) }
    }

    /** Start again (another server, or signed in again). */
    fun restart() { stop(); start() }

    private fun connect() {
        val base = server() ?: return
        val gen = ++generation
        _ui.update { it.copy(selfId = identity.id) }
        val request = runCatching { Request.Builder().url("$base/api/connect").build() }.getOrNull() ?: return
        socket = http.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                webSocket.send(JsonObject(mapOf("type" to JsonPrimitive("hello"), "id" to JsonPrimitive(identity.id),
                    "name" to JsonPrimitive(identity.name), "kind" to JsonPrimitive(identity.kind))).toString())
            }
            override fun onMessage(webSocket: WebSocket, text: String) {
                val msg = parseIncoming(text) ?: return
                post { if (gen == generation) handle(msg) }
            }
            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                // The server is closing (it restarted, say): answer, and count it as dropped straight away.
                webSocket.close(1000, null)
                post { if (gen == generation) dropped() }
            }
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) = post { if (gen == generation) dropped() }
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) = post { if (gen == generation) dropped() }
        })
    }

    private fun dropped() {
        socket = null
        _ui.update { it.copy(connected = false) }
        if (!started) return
        val delay = min(30_000L, 1000L shl min(retry, 5))
        retry++
        val gen = generation
        schedule(delay) { if (started && socket == null && gen == generation) connect() }
    }

    private fun handle(msg: Incoming) {
        when (msg) {
            is Incoming.Welcome -> {
                retry = 0
                _ui.update { it.copy(connected = true, selfId = identity.id, devices = msg.devices, activeId = msg.active,
                    state = msg.state ?: it.state, queue = msg.queue ?: it.queue, at = clock()) }
                flushHeld()
                listener?.onConnected()
            }
            is Incoming.Devices -> _ui.update { it.copy(devices = msg.devices, activeId = msg.active) }
            is Incoming.State -> _ui.update { it.copy(state = msg.state, queue = msg.queue ?: it.queue, at = clock()) }
            is Incoming.Cmd -> listener?.onCmd(msg.name, msg.args)
            is Incoming.Takeover -> listener?.onTakeover(msg.snapshot)
            Incoming.Release -> listener?.onRelease()
            Incoming.Duplicate -> {
                // Another device has this id (a restored backup, say): take a new one and connect again.
                identity.renew()
                generation++
                socket?.close(1000, null)
                socket = null
                connect()
            }
            is Incoming.Notice -> listener?.onNotice(msg.text)
        }
    }

    private fun flushHeld() {
        val now = clock()
        val fresh = held.filter { now - it.first < 60_000 }.map { it.second }
        held.clear()
        if (_ui.value.remote) fresh.forEach { socket?.send(it.toString()) }
    }

    /** Send a message now, if connected (reports aren't worth keeping). */
    fun send(msg: JsonObject) { post { if (_ui.value.connected) socket?.send(msg.toString()) } }

    /** Control the playing device. Held for up to a minute while the connection is down. */
    fun cmd(name: String, vararg args: JsonElement) {
        val msg = JsonObject(mapOf("type" to JsonPrimitive("cmd"), "name" to JsonPrimitive(name), "args" to JsonArray(args.toList())))
        post {
            if (_ui.value.connected && socket != null) socket?.send(msg.toString()) else held.addLast(clock() to msg)
        }
    }

    /** Show a control's effect straight away, before the playing device confirms it. */
    fun optimistic(change: (RemoteState) -> RemoteState) =
        _ui.update { u -> u.state?.let { s -> u.copy(state = change(s), at = clock()) } ?: u }
}
