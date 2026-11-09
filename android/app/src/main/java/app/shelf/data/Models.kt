package app.shelf.data

import kotlinx.serialization.Serializable

// What the server sends (src/shelf/app.py: album_json, track_json, …). Fields the app doesn't
// use are ignored, so a newer server doesn't break an older app.

@Serializable data class User(val id: Int, val username: String, val admin: Boolean = false)

@Serializable data class Session(val setup: Boolean = false, val signedIn: Boolean = false, val user: User? = null, val version: String = "")

@Serializable data class LoginResult(val token: String, val user: User)

@Serializable
data class Album(
    val id: Int, val title: String, val artist: String, val artists: List<String> = emptyList(),
    val year: Int? = null, val genre: String? = null, val trackCount: Int = 0, val duration: Double = 0.0,
    val color: String? = null, val cover: String? = null,
)

@Serializable
data class AlbumDetail(
    val id: Int, val title: String, val artist: String, val artists: List<String> = emptyList(),
    val year: Int? = null, val genre: String? = null, val trackCount: Int = 0, val duration: Double = 0.0,
    val color: String? = null, val cover: String? = null, val tracks: List<Track> = emptyList(),
)

@Serializable
data class Track(
    val id: Int, val title: String, val artist: String, val artists: List<String> = emptyList(),
    val album: String = "", val albumId: Int, val albumArtist: String? = null, val cover: String? = null,
    val trackNo: Int? = null, val discNo: Int? = null, val duration: Double = 0.0, val codec: String? = null,
    val bits: Int? = null, val sampleRate: Int? = null, val lufs: Double? = null, val peak: Double? = null,
)

@Serializable data class ArtistSummary(val name: String, val albums: Int = 0, val tracks: Int = 0, val coverAlbumId: Int? = null, val cover: String? = null)

@Serializable
data class ArtistPage(
    val name: String, val albums: List<Album> = emptyList(), val popular: List<Track> = emptyList(),
    val appearsOn: List<Album> = emptyList(),
)

@Serializable data class CoverRef(val albumId: Int, val cover: String? = null)

@Serializable
data class PlaylistSummary(
    val id: Int, val name: String, val description: String? = null, val trackCount: Int = 0,
    val duration: Double = 0.0, val covers: List<CoverRef> = emptyList(), val canEdit: Boolean = false,
)

@Serializable
data class PlaylistDetail(
    val id: Int, val name: String, val description: String? = null, val trackCount: Int = 0,
    val duration: Double = 0.0, val covers: List<CoverRef> = emptyList(), val canEdit: Boolean = false,
    val tracks: List<Track> = emptyList(),
)

@Serializable
data class MixSummary(
    val key: String, val name: String, val description: String = "", val color: String? = null,
    val kind: String = "", val covers: List<CoverRef> = emptyList(),
)

@Serializable
data class MixDetail(
    val key: String, val name: String, val description: String = "", val color: String? = null,
    val kind: String = "", val covers: List<CoverRef> = emptyList(), val tracks: List<Track> = emptyList(),
)

@Serializable data class Home(val recent: List<Album> = emptyList(), val added: List<Album> = emptyList(), val rediscover: List<Album> = emptyList())

@Serializable data class SearchArtist(val name: String, val albums: Int = 0)

@Serializable
data class SearchResults(val artists: List<SearchArtist> = emptyList(), val albums: List<Album> = emptyList(), val tracks: List<Track> = emptyList()) {
    val isEmpty get() = artists.isEmpty() && albums.isEmpty() && tracks.isEmpty()
}
