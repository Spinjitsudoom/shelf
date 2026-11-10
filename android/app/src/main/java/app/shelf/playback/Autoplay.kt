package app.shelf.playback

import app.shelf.data.Track

/**
 * Autoplay, as the web app does it: when the queue is about to run out (and repeat is off), add
 * up to 25 similar songs from the library that weren't among the last 200 played.
 */
fun autoplayPick(queueIds: List<Int>, similar: List<Track>, repeatOff: Boolean): List<Track> {
    if (!repeatOff) return emptyList()
    val recent = queueIds.takeLast(200).toSet()
    return similar.filter { it.id !in recent }.distinctBy { it.id }.take(25)
}
