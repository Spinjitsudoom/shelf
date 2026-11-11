package app.shelf.whatsnew

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class WhatsNewTest {
    private val notes = parseNotes("""[
        {"version": "0.8.0", "new": [{"title": "Big thing", "text": "It's big."}, {"title": "Backups", "text": "For admins.", "admin": true}], "fixed": ["A bug"]},
        {"version": "0.7.6", "fixed": ["Another bug"]},
        {"version": "0.7.5", "new": [{"title": "Smart playlists", "text": "Rules."}]}
    ]""")

    /** Once after an update: what changed since the version last shown, never on a new install. */
    @Test fun showsWhatChangedOnceAfterAnUpdate() {
        assertEquals(listOf("0.8.0", "0.7.6"), toShow(notes, seen = "0.7.5", current = "0.8.0", updated = true).map { it.version })
        assertEquals(emptyList<String>(), toShow(notes, seen = "0.8.0", current = "0.8.0", updated = true).map { it.version })
        // The first version with this window: nothing was recorded yet, but the app was updated.
        assertEquals(listOf("0.8.0"), toShow(notes, seen = null, current = "0.8.0", updated = true).map { it.version })
        // A new install: nothing.
        assertTrue(toShow(notes, seen = null, current = "0.8.0", updated = false).isEmpty())
    }

    @Test fun adminOnlyItemsAreForAdmins() {
        assertEquals(listOf("Big thing"), notes[0].forPerson(admin = false).new.map { it.title })
        assertEquals(listOf("Big thing", "Backups"), notes[0].forPerson(admin = true).new.map { it.title })
    }

    @Test fun versionsCompareAsNumbers() {
        assertTrue(newer("0.10.0", "0.9.9"))
        assertTrue(!newer("0.7.5", "0.7.5"))
    }
}
