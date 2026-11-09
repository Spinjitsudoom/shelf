package app.shelf.data

/** Where the screens get the library from: the server (ShelfApi), or a fake in tests. */
interface LibrarySource {
    suspend fun home(): Home
    suspend fun albums(sort: String = "recent"): List<Album>
    suspend fun album(id: Int): AlbumDetail
    suspend fun artists(): List<ArtistSummary>
    suspend fun artist(name: String): ArtistPage
    suspend fun playlists(): List<PlaylistSummary>
    suspend fun playlist(id: Int): PlaylistDetail
    suspend fun likes(): List<Track>
    suspend fun mixes(): List<MixSummary>
    suspend fun mix(key: String): MixDetail
    fun coverUrl(albumId: Int, version: String?, size: Int): String?
}
