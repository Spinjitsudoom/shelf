package app.shelf.playback

import kotlinx.serialization.Serializable

/** Where the music being played came from: shown as "Playing from …" and opened from there. */
@Serializable
data class PlayContext(val label: String, val route: String, val mix: Boolean = false)
