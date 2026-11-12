package app.shelf

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.widget.Toast
import app.shelf.ui.common.sharedPlaylistLink

/**
 * Where a playlist link shared from another app (Spotify, YouTube) lands: it's handed to the app,
 * which opens Import a playlist with it, the way tapping Shelf's icon would open the app.
 */
class ShareActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val text = intent?.takeIf { it.action == Intent.ACTION_SEND }?.getStringExtra(Intent.EXTRA_TEXT).orEmpty()
        val link = sharedPlaylistLink(text)
        if (link == null) {
            Toast.makeText(this, "Shelf can import Spotify and YouTube playlist links", Toast.LENGTH_LONG).show()
        } else {
            (application as ShelfApp).container.sharedImport.value = link
            startActivity(Intent(this, MainActivity::class.java).apply {
                action = Intent.ACTION_MAIN
                addCategory(Intent.CATEGORY_LAUNCHER)
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED)
            })
        }
        finish()
    }
}
