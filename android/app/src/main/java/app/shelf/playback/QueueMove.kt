package app.shelf.playback

/**
 * Moving a song in the queue: only songs still to come move, and only among themselves (the
 * playing song and the ones already played stay where they are). A drop above them lands first
 * up next; past the end, last. Returns (from, to) as Media3's moveMediaItem takes them, or null
 * when there's nothing to move.
 */
fun queueMove(size: Int, current: Int, from: Int, to: Int): Pair<Int, Int>? {
    if (from <= current || from >= size) return null
    val target = to.coerceIn(current + 1, size - 1)
    return if (target == from) null else from to target
}
