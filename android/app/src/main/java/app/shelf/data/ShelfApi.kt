package app.shelf.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.DeserializationStrategy
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException

/** Talks to one Shelf server's API (src/shelf/app.py), signed in with [tokenProvider]'s token. */
class ShelfApi(private val base: HttpUrl, private val tokenProvider: () -> String?, private val client: OkHttpClient) {
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

    suspend fun home(): Home = call("api/home", Home.serializer())
    suspend fun albums(sort: String = "recent"): List<Album> = call("api/albums?sort=$sort", ListSerializer(Album.serializer()))
    suspend fun album(id: Int): AlbumDetail = call("api/albums/$id", AlbumDetail.serializer())
    suspend fun artists(): List<ArtistSummary> = call("api/artists", ListSerializer(ArtistSummary.serializer()))
    suspend fun artist(name: String): ArtistPage = call(url("api/artist").newBuilder().addQueryParameter("name", name).build(), ArtistPage.serializer())
    suspend fun playlists(): List<PlaylistSummary> = call("api/playlists", ListSerializer(PlaylistSummary.serializer()))
    suspend fun playlist(id: Int): PlaylistDetail = call("api/playlists/$id", PlaylistDetail.serializer())
    suspend fun likes(): List<Track> = call("api/likes", ListSerializer(Track.serializer()))
    suspend fun mixes(): List<MixSummary> = call("api/mixes", ListSerializer(MixSummary.serializer()))
    suspend fun mix(key: String): MixDetail = call(url("api/mixes").newBuilder().addPathSegment(key).build(), MixDetail.serializer())

    /** A listen, for history, mixes and recommendations. */
    suspend fun played(trackId: Int) {
        call("api/tracks/$trackId/played", JsonObject.serializer(), ByteArray(0).toRequestBody(null))
    }

    /** An album cover at `size` px, or null when the album has none. */
    fun coverUrl(albumId: Int, version: String?, size: Int): String? =
        version?.let { url("api/albums/$albumId/cover?size=$size&v=$it").toString() }

    fun streamUrl(trackId: Int, quality: String): String = url("api/tracks/$trackId/stream?q=$quality").toString()

    private fun url(path: String): HttpUrl = base.resolve(path) ?: throw IllegalArgumentException(path)

    private suspend fun <T> call(path: String, type: DeserializationStrategy<T>, post: RequestBody? = null): T = call(url(path), type, post)

    private suspend fun <T> call(target: HttpUrl, type: DeserializationStrategy<T>, post: RequestBody? = null): T = withContext(Dispatchers.IO) {
        val req = Request.Builder().url(target).apply {
            tokenProvider()?.let { header("Authorization", "Bearer $it") }
            if (post != null) post(post)
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
