package app.shelf.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.DeserializationStrategy
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.add
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException

/** Talks to one Shelf server's API (src/shelf/app.py), signed in with [tokenProvider]'s token. */
class ShelfApi(private val base: HttpUrl, private val tokenProvider: () -> String?, private val client: OkHttpClient) : LibrarySource, LikesApi {
    private val json = Json { ignoreUnknownKeys = true; coerceInputValues = true; explicitNulls = false }

    suspend fun ping(): String {
        val body = try { call("api/ping", JsonObject.serializer()) } catch (e: ShelfError.Server) { throw ShelfError.NotShelf() }
            catch (e: kotlinx.serialization.SerializationException) { throw ShelfError.NotShelf() }
        if (body["app"]?.jsonPrimitive?.content != "shelf") throw ShelfError.NotShelf()
        return body["version"]?.jsonPrimitive?.content ?: ""
    }

    suspend fun session(): Session = call("api/session", Session.serializer())

    /** Sign in; returns the token to send from now on, and who signed in. */
    suspend fun login(username: String, password: String): Pair<String, User> {
        val body = buildJsonObject { put("username", username); put("password", password) }
        val r = call("api/login", LoginResult.serializer(), body.toString().toRequestBody(JSON))
        return r.token to r.user
    }

    override suspend fun home(): Home = call("api/home", Home.serializer())
    override suspend fun albums(sort: String): List<Album> = call("api/albums?sort=$sort", ListSerializer(Album.serializer()))
    override suspend fun album(id: Int): AlbumDetail = call("api/albums/$id", AlbumDetail.serializer())
    suspend fun lyrics(id: Int): Lyrics = call("api/tracks/$id/lyrics", Lyrics.serializer())
    suspend fun similar(id: Int): List<Track> = call("api/tracks/$id/similar?limit=40", ListSerializer(Track.serializer()))
    suspend fun setShareActivity(on: Boolean) = send("PATCH", "api/me", buildJsonObject { put("shareActivity", on) }.toString())
    suspend fun people(): List<Person> = call("api/people", ListSerializer(Person.serializer()))
    suspend fun blend(otherId: Int): MixDetail = call("api/blend/$otherId", MixDetail.serializer())
    // ---- party mode ----
    suspend fun parties(): List<PartySummary> = call("api/parties", ListSerializer(PartySummary.serializer()))
    /** Start a party; returns the host's id (yours), to open it. */
    suspend fun startParty(): Int = call("api/party", JsonObject.serializer(), "{}".toRequestBody(JSON))["host"].toString().toInt()
    suspend fun endParty() { send("DELETE", "api/party") }
    suspend fun party(host: Int): PartyStatus = call(url("api/party/$host"), PartyStatus.serializer(), null, "GET")
    suspend fun joinParty(host: Int) { send("POST", "api/party/$host/join") }
    suspend fun leaveParty(host: Int) { send("POST", "api/party/$host/leave") }
    suspend fun partyAdd(host: Int, trackIds: List<Int>) { send("POST", "api/party/$host/add", buildJsonObject { putJsonArray("trackIds") { trackIds.forEach { add(it) } } }.toString()) }
    suspend fun partySkip(host: Int): SkipVote = call("api/party/$host/skip", SkipVote.serializer(), "{}".toRequestBody(JSON))

    suspend fun activity(): List<Activity> = call("api/activity", ListSerializer(Activity.serializer()))
    suspend fun video(id: Int): VideoInfo = call("api/tracks/$id/video", VideoInfo.serializer())
    override suspend fun artists(): List<ArtistSummary> = call("api/artists", ListSerializer(ArtistSummary.serializer()))
    override suspend fun artist(name: String): ArtistPage = call(url("api/artist").newBuilder().addQueryParameter("name", name).build(), ArtistPage.serializer())
    override suspend fun playlists(): List<PlaylistSummary> = call("api/playlists", ListSerializer(PlaylistSummary.serializer()))
    override suspend fun playlist(id: Int): PlaylistDetail = call("api/playlists/$id", PlaylistDetail.serializer())
    override suspend fun likes(): List<Track> = call("api/likes", ListSerializer(Track.serializer()))
    override suspend fun mixes(): List<MixSummary> = call("api/mixes", ListSerializer(MixSummary.serializer()))
    override suspend fun mix(key: String): MixDetail = call(url("api/mixes").newBuilder().addPathSegment(key).build(), MixDetail.serializer())

    override suspend fun likeIds(): List<Int> = call("api/likes/ids", ListSerializer(Int.serializer()))
    override suspend fun like(trackId: Int) { send("PUT", "api/likes/$trackId") }
    override suspend fun unlike(trackId: Int) { send("DELETE", "api/likes/$trackId") }

    suspend fun search(q: String): SearchResults = call(url("api/search").newBuilder().addQueryParameter("q", q).build(), SearchResults.serializer())

    // ---- playlists ----
    suspend fun createPlaylist(name: String, trackIds: List<Int> = emptyList(), description: String? = null): PlaylistSummary =
        call("api/playlists", PlaylistSummary.serializer(), body {
            put("name", name); putJsonArray("trackIds") { trackIds.forEach { add(it) } }; description?.let { put("description", it) }
        })
    /** Songs for a playlist from a few words ("metal, high energy"); a ShelfError.Server says why not. */
    suspend fun makePlaylist(prompt: String, size: Int = 30): MadePlaylist =
        call("api/playlists/make", MadePlaylist.serializer(), body { put("prompt", prompt); put("size", size) })
    suspend fun editPlaylist(id: Int, name: String? = null, description: String? = null) =
        send("PATCH", "api/playlists/$id", buildJsonObject { name?.let { put("name", it) }; description?.let { put("description", it) } }.toString())
    suspend fun deletePlaylist(id: Int) = send("DELETE", "api/playlists/$id")
    suspend fun setTransition(playlistId: Int, entryId: Int, choice: app.shelf.playback.TransitionChoice) =
        send("PUT", "api/playlists/$playlistId/tracks/$entryId/transition", choice.body().toString())
    suspend fun setPlaylistMix(id: Int, on: Boolean) = send("PATCH", "api/playlists/$id", buildJsonObject { put("mix", on) }.toString())
    suspend fun addToPlaylist(id: Int, trackIds: List<Int>): PlaylistSummary =
        call("api/playlists/$id/tracks", PlaylistSummary.serializer(), body { putJsonArray("trackIds") { trackIds.forEach { add(it) } } })
    suspend fun removeFromPlaylist(id: Int, entryId: Int) = send("DELETE", "api/playlists/$id/tracks/$entryId")
    suspend fun reorderPlaylist(id: Int, entryIds: List<Int>) =
        send("PUT", "api/playlists/$id/order", buildJsonObject { putJsonArray("entryIds") { entryIds.forEach { add(it) } } }.toString())

    /** Song or artist radio: the seed, then songs from across the library that fit it. */
    suspend fun radio(track: Int? = null, artist: String? = null): MixDetail = call(url("api/radio").newBuilder().apply {
        track?.let { addQueryParameter("track", it.toString()) }; artist?.let { addQueryParameter("artist", it) }
    }.build(), MixDetail.serializer())

    private fun body(build: kotlinx.serialization.json.JsonObjectBuilder.() -> Unit) = buildJsonObject(build).toString().toRequestBody(JSON)

    /** Your listening for a period ("month", "year", "all" or a year), in this phone's time zone. */
    suspend fun stats(period: String, tzMinutes: Int = java.util.TimeZone.getDefault().getOffset(System.currentTimeMillis()) / 60_000): ListeningStats =
        call(url("api/stats").newBuilder().addQueryParameter("period", period).addQueryParameter("tz", tzMinutes.toString()).build(),
            ListeningStats.serializer())

    /** Moved on before 30 seconds of it: suggestions learn from skips. */
    suspend fun skipped(trackId: Int) { send("POST", "api/tracks/$trackId/skipped") }

    /** A listen, for history, mixes and recommendations. */
    suspend fun played(trackId: Int) {
        call("api/tracks/$trackId/played", JsonObject.serializer(), ByteArray(0).toRequestBody(null))
    }

    /** An album cover at `size` px, or null when the album has none. */
    override fun coverUrl(albumId: Int, version: String?, size: Int): String? =
        version?.let { url("api/albums/$albumId/cover?size=$size&v=$it").toString() }

    fun streamUrl(trackId: Int, quality: String): String = url("api/tracks/$trackId/stream?q=$quality").toString()

    /** A request whose answer isn't needed (PUT, DELETE, PATCH, POST): errors still throw. */
    private suspend fun send(method: String, path: String, body: String? = null) {
        call(url(path), JsonObject.serializer(), (body ?: "{}").toRequestBody(JSON), method)
    }

    private fun url(path: String): HttpUrl = base.resolve(path) ?: throw IllegalArgumentException(path)

    private suspend fun <T> call(path: String, type: DeserializationStrategy<T>, post: RequestBody? = null): T = call(url(path), type, post)

    private suspend fun <T> call(target: HttpUrl, type: DeserializationStrategy<T>, post: RequestBody? = null, method: String = "POST"): T = withContext(Dispatchers.IO) {
        val req = Request.Builder().url(target).apply {
            tokenProvider()?.let { header("Authorization", "Bearer $it") }
            if (post != null) method(method, post)
        }.build()
        val res = try { client.newCall(req).execute() } catch (e: IOException) { throw ShelfError.Offline(e) }
        res.use {
            val text = try { it.body.string() } catch (e: IOException) { throw ShelfError.Offline(e) }
            when {
                it.code == 401 -> throw ShelfError.SignedOut()
                !it.isSuccessful -> throw ShelfError.Server(it.code, detail(text) ?: "The server said no (${it.code})")
                else -> json.decodeFromString(type, text)
            }
        }
    }

    private fun detail(text: String): String? = try {
        (json.parseToJsonElement(text) as? JsonObject)?.get("detail")?.let { d -> (d as? kotlinx.serialization.json.JsonPrimitive)?.content }
    } catch (e: Exception) { null }

    companion object {
        private val JSON = "application/json".toMediaType()
    }
}

/** What was typed ("192.168.1.20:4533", "shelf.home/") as a full address, or null. The same rules as the web app's server.js. */
fun normalizeServer(input: String): String? {
    var s = input.trim()
    if (s.isEmpty()) return null
    if (!Regex("^[a-z][a-z0-9+.-]*://", RegexOption.IGNORE_CASE).containsMatchIn(s)) s = "http://$s"
    val u = s.toHttpUrlOrNull() ?: return null
    if (u.host.isEmpty()) return null
    val defaultPort = HttpUrl.defaultPort(u.scheme)
    val origin = "${u.scheme}://${u.host}" + (if (u.port != defaultPort) ":${u.port}" else "")
    return origin + u.encodedPath.replace(Regex("/(index\\.html)?$"), "")
}
