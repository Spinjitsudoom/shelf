package app.shelf.ui.common

import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class MakeWordsTest {
    @Test fun makesWithTheWordsAndShowsWhyNot() = runTest {
        val asked = mutableListOf<String>()
        val form = MakeWords()
        val onMake: suspend (String) -> String? = { asked += it; if (it == "zzz") "Shelf didn’t recognise any of that." else null }

        assertFalse(form.submit(onMake))
        assertEquals("Describe the playlist first.", form.error) // nothing typed yet
        assertTrue(asked.isEmpty())

        form.type("  zzz ")
        assertNull(form.error) // typing clears it
        assertFalse(form.submit(onMake))
        assertEquals("Shelf didn’t recognise any of that.", form.error)
        assertEquals(listOf("zzz"), asked)
        assertFalse(form.working)

        form.type("metal")
        assertTrue(form.submit(onMake)) // made: the dialog closes
    }
}
