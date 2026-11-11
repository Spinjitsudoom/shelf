package app.shelf;

import android.app.Activity;
import android.app.PendingIntent;
import android.content.Intent;
import android.content.pm.PackageInstaller;
import android.os.Build;
import android.os.Bundle;
import android.widget.Toast;

import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.io.OutputStream;

/**
 * Installs a downloaded update: opened from the "Shelf X is ready" notification. It has no
 * screen of its own; it hands the APK to Android's package installer, shows Android's "Do you
 * want to update this app?" confirmation, and closes.
 */
public class UpdateActivity extends Activity {
    static final String ACTION_INSTALL = "app.shelf.INSTALL_UPDATE";
    private static final String ACTION_STATUS = "app.shelf.UPDATE_STATUS";

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        handle(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        handle(intent);
    }

    private void handle(Intent intent) {
        String action = intent == null ? null : intent.getAction();
        if (ACTION_STATUS.equals(action)) {
            status(intent);
        } else if (ACTION_INSTALL.equals(action)) {
            install();
        } else {
            finish();
        }
    }

    private void install() {
        File apk = new File(getCacheDir(), "update.apk");
        if (!apk.exists()) {
            Toast.makeText(this, "The update isn’t downloaded any more. Shelf will fetch it again.", Toast.LENGTH_LONG).show();
            Updater.checkSoon(this);
            finish();
            return;
        }
        Updater.clearNotification(this);
        if ("xiaomi".equalsIgnoreCase(Build.MANUFACTURER)) { systemInstaller(); return; } // MIUI turns down direct installs
        try {
            PackageInstaller installer = getPackageManager().getPackageInstaller();
            PackageInstaller.SessionParams params = new PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL);
            params.setAppPackageName(getPackageName());
            int id = installer.createSession(params);
            try (PackageInstaller.Session session = installer.openSession(id)) {
                try (InputStream in = new FileInputStream(apk); OutputStream out = session.openWrite("shelf.apk", 0, apk.length())) {
                    byte[] buf = new byte[65536];
                    for (int n; (n = in.read(buf)) > 0; ) out.write(buf, 0, n);
                    session.fsync(out);
                }
                Intent back = new Intent(this, UpdateActivity.class).setAction(ACTION_STATUS);
                int flags = PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= 31 ? PendingIntent.FLAG_MUTABLE : 0);
                session.commit(PendingIntent.getActivity(this, 1, back, flags).getIntentSender());
            }
        } catch (Exception e) {
            systemInstaller(); // installing directly didn't work here: Android's installer screen instead
        }
    }

    /** Android's own "update this app?" screen, given the downloaded APK. */
    private void systemInstaller() {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW).setDataAndType(ApkProvider.uri(this), "application/vnd.android.package-archive")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK));
        } catch (Exception e) {
            Toast.makeText(this, "Couldn’t install the update: " + e.getMessage(), Toast.LENGTH_LONG).show();
        }
        finish();
    }

    @SuppressWarnings("deprecation")
    private void status(Intent intent) {
        int status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE);
        if (status == PackageInstaller.STATUS_PENDING_USER_ACTION) {
            Intent confirm = intent.getParcelableExtra(Intent.EXTRA_INTENT);
            if (confirm != null) startActivity(confirm); // Android's "update this app?" screen
            return;
        }
        if (status != PackageInstaller.STATUS_SUCCESS && status != PackageInstaller.STATUS_FAILURE_ABORTED) {
            // Turned down here (MIUI says "Permission Denied", for one): Android's installer screen instead.
            if (new File(getCacheDir(), "update.apk").exists()) { systemInstaller(); return; }
            String msg = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE);
            Toast.makeText(this, "The update didn’t install" + (msg != null ? ": " + msg : ""), Toast.LENGTH_LONG).show();
        }
        finish();
    }
}
