package app.shelf.playback

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/** A sleep timer that's on: it ends at [endsAt], or at the end of the song that's playing. */
data class SleepState(val endsAt: Long?, val endOfSong: Boolean)

private const val FADE_MS = 8_000L

/**
 * Stops the music after a while, or at the end of the song, as the web app's sleep timer does.
 * The music fades out over the last 8 seconds rather than cutting off. The player service drives
 * it ([onTick] for the fade, [onSongEnded] when a song plays to its end), so it works with the
 * screen off and the app closed.
 */
class SleepTimer(private val clock: () -> Long = System::currentTimeMillis) {
    val choices = listOf(5, 15, 30, 45, 60, 90)
    private val _state = MutableStateFlow<SleepState?>(null)
    val state: StateFlow<SleepState?> = _state
    /** Called when it's time to stop (the service pauses the music). */
    var onStop: () -> Unit = {}

    fun set(minutes: Int) { _state.value = SleepState(clock() + minutes * 60_000L, false) }
    fun endOfSong() { _state.value = SleepState(null, true) }
    fun cancel() { _state.value = null }

    /** The volume for now: 1, falling to 0 over the last 8 seconds. At the end it stops the music and gives 1 back for next time. */
    fun onTick(): Float {
        val end = _state.value?.endsAt ?: return 1f
        val left = end - clock()
        if (left <= 0) { stop(); return 1f }
        return if (left < FADE_MS) left.toFloat() / FADE_MS else 1f
    }

    /** The song that was playing reached its end (not a skip). */
    fun onSongEnded() { if (_state.value?.endOfSong == true) stop() }

    private fun stop() { _state.value = null; onStop() }
}
