package app.shelf;

import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.os.Build;
import android.widget.RemoteViews;

/**
 * The home-screen widget: the cover, song and artist, with previous, play/pause and next.
 * PlaybackService pushes every change here. With nothing loaded (or the app closed), it says
 * so, and any tap opens Shelf.
 */
public class NowPlayingWidget extends AppWidgetProvider {

    @Override
    public void onUpdate(Context context, AppWidgetManager manager, int[] ids) {
        push(context, PlaybackService.current(), PlaybackService.currentArt());
    }

    /** Draw every Shelf widget for this state (null: nothing playing). */
    static void push(Context context, PlaybackService.State s, Bitmap art) {
        AppWidgetManager manager = AppWidgetManager.getInstance(context);
        ComponentName me = new ComponentName(context, NowPlayingWidget.class);
        int[] ids = manager.getAppWidgetIds(me);
        if (ids == null || ids.length == 0) return;

        RemoteViews v = new RemoteViews(context.getPackageName(), R.layout.widget_now_playing);
        PendingIntent open = PendingIntent.getActivity(context, 10,
            new Intent(context, MainActivity.class).setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_UPDATE_CURRENT | immutable());
        v.setOnClickPendingIntent(R.id.widget_root, open);
        v.setOnClickPendingIntent(R.id.widget_art, open);

        if (s == null) {
            v.setTextViewText(R.id.widget_title, "Shelf");
            v.setTextViewText(R.id.widget_artist, "Nothing playing. Tap to open");
            v.setImageViewResource(R.id.widget_art, R.mipmap.ic_launcher);
            v.setImageViewResource(R.id.widget_play, R.drawable.ic_play_dark);
            v.setContentDescription(R.id.widget_play, "Open Shelf");
            // With the app closed there's no player to command, so every button opens it.
            v.setOnClickPendingIntent(R.id.widget_play, open);
            v.setOnClickPendingIntent(R.id.widget_prev, open);
            v.setOnClickPendingIntent(R.id.widget_next, open);
        } else {
            v.setTextViewText(R.id.widget_title, s.title);
            v.setTextViewText(R.id.widget_artist, s.device.isEmpty() ? s.artist : s.artist + " • on " + s.device);
            if (art != null) v.setImageViewBitmap(R.id.widget_art, art);
            else v.setImageViewResource(R.id.widget_art, R.mipmap.ic_launcher);
            v.setImageViewResource(R.id.widget_play, s.playing ? R.drawable.ic_pause_dark : R.drawable.ic_play_dark);
            v.setContentDescription(R.id.widget_play, s.playing ? "Pause" : "Play");
            v.setOnClickPendingIntent(R.id.widget_play, command(context, s.playing ? "pause" : "play"));
            v.setOnClickPendingIntent(R.id.widget_prev, command(context, "prev"));
            v.setOnClickPendingIntent(R.id.widget_next, command(context, "next"));
        }
        manager.updateAppWidget(ids, v);
    }

    /** A button press, delivered to the playback service (started in the foreground if need be). */
    private static PendingIntent command(Context context, String name) {
        Intent i = new Intent(context, PlaybackService.class)
            .setAction(PlaybackService.ACTION_COMMAND)
            .putExtra("cmd", name)
            .putExtra("foreground", true);
        int code = 100 + name.hashCode() % 1000;
        if (Build.VERSION.SDK_INT >= 26) {
            return PendingIntent.getForegroundService(context, code, i, PendingIntent.FLAG_UPDATE_CURRENT | immutable());
        }
        return PendingIntent.getService(context, code, i, PendingIntent.FLAG_UPDATE_CURRENT | immutable());
    }

    private static int immutable() {
        return Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_IMMUTABLE : 0;
    }
}
