package app.shelf

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.view.KeyEvent
import android.widget.RemoteViews
import androidx.annotation.OptIn
import androidx.media3.common.util.UnstableApi
import androidx.media3.session.MediaButtonReceiver
import app.shelf.data.Track

/** The widget's two lines: the song and who it's by (and where it plays, when that's another device). */
fun widgetText(track: Track?, device: String?): Pair<String, String> = when {
    track == null -> "Shelf" to "Tap to open"
    device != null -> track.title to "${track.artist}, on $device"
    else -> track.title to track.artist
}

/** What the widget shows: a song, whether it's playing, and the device it plays on (null: this phone). */
data class WidgetState(val track: Track, val playing: Boolean, val device: String?)

/**
 * The home-screen widget: the cover, song and artist, with previous, play/pause and next.
 * The player service pushes every change. The buttons are media-button presses, so they work
 * like headphone buttons: with Shelf closed, play picks up where it left off.
 *
 * (Its class name is the WebView app's, so widgets already on home screens keep working.)
 */
@OptIn(UnstableApi::class)
class NowPlayingWidget : AppWidgetProvider() {
    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) = push(context, last, lastArt)

    companion object {
        @Volatile private var last: WidgetState? = null
        @Volatile private var lastArt: Bitmap? = null

        /** Draw every Shelf widget for this state (null: nothing playing). */
        fun push(context: Context, state: WidgetState?, art: Bitmap?) {
            last = state; lastArt = art
            val manager = AppWidgetManager.getInstance(context)
            val ids = manager.getAppWidgetIds(ComponentName(context, NowPlayingWidget::class.java))
            if (ids == null || ids.isEmpty()) return
            val v = RemoteViews(context.packageName, R.layout.widget_now_playing)
            val open = PendingIntent.getActivity(context, 10,
                Intent(context, MainActivity::class.java).setFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
            v.setOnClickPendingIntent(R.id.widget_root, open)
            v.setOnClickPendingIntent(R.id.widget_art, open)
            val (title, subtitle) = widgetText(state?.track, state?.device)
            v.setTextViewText(R.id.widget_title, title)
            v.setTextViewText(R.id.widget_artist, subtitle)
            if (art != null) v.setImageViewBitmap(R.id.widget_art, art) else v.setImageViewResource(R.id.widget_art, R.mipmap.ic_launcher)
            val playing = state?.playing == true
            v.setImageViewResource(R.id.widget_play, if (playing) R.drawable.widget_pause_dark else R.drawable.widget_play_dark)
            v.setContentDescription(R.id.widget_play, if (playing) "Pause" else "Play")
            v.setOnClickPendingIntent(R.id.widget_play, key(context, KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE))
            if (state == null) {
                // Nothing loaded: skipping means nothing, so these open Shelf.
                v.setOnClickPendingIntent(R.id.widget_prev, open)
                v.setOnClickPendingIntent(R.id.widget_next, open)
            } else {
                v.setOnClickPendingIntent(R.id.widget_prev, key(context, KeyEvent.KEYCODE_MEDIA_PREVIOUS))
                v.setOnClickPendingIntent(R.id.widget_next, key(context, KeyEvent.KEYCODE_MEDIA_NEXT))
            }
            manager.updateAppWidget(ids, v)
        }

        /** A media-button press, handed to the player service by Media3's receiver (which starts it if need be). */
        private fun key(context: Context, code: Int): PendingIntent {
            val i = Intent(Intent.ACTION_MEDIA_BUTTON).setComponent(ComponentName(context, MediaButtonReceiver::class.java))
                .putExtra(Intent.EXTRA_KEY_EVENT, KeyEvent(KeyEvent.ACTION_DOWN, code))
            return PendingIntent.getBroadcast(context, 200 + code, i, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        }
    }
}
