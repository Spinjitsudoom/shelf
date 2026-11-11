package app.shelf.data

import okhttp3.HttpUrl.Companion.toHttpUrl
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SecureMoveTest {
    private val secure = "https://shelf-pc.example.ts.net"

    @Test fun homeAndTailnetAddressesArePrivate() {
        for (h in listOf("localhost", "127.0.0.1", "192.168.0.64", "10.0.0.5", "172.20.1.1", "100.64.132.58",
            "desktop-apr1r4t", "nas.local", "::1", "fd7a:115c:a1e0::1", "169.254.3.4", "pc.tailaa519a.ts.net"))
            assertTrue(h, isPrivateHost(h))
        for (h in listOf("77.71.156.41", "8.8.8.8", "172.32.0.1", "music.duckdns.org", "2a00:1450::1"))
            assertFalse(h, isPrivateHost(h))
    }

    @Test fun plainHttpFromTheInternetMovesToTheSecureAddress() {
        assertEquals(secure, secureMoveTarget("http://77.71.156.41:4533", secure))
        assertEquals(secure, secureMoveTarget("http://77.71.156.41:4533", "$secure/"))
    }

    @Test fun staysPutAtHomeOnHttpsOrWithoutOne() {
        assertNull(secureMoveTarget("http://192.168.0.64:4533", secure))
        assertNull(secureMoveTarget("https://music.example.org", secure))
        assertNull(secureMoveTarget("http://77.71.156.41:4533", null))
        assertNull(secureMoveTarget("http://77.71.156.41:4533", "http://plain.example.org"))
        assertNull(secureMoveTarget(secure, secure))
    }

    @Test fun requestsToTheOldAddressGoToTheNewOne() {
        val now = secure.toHttpUrl()
        val former = setOf("http://77.71.156.41:4533")
        val moved = rebase("http://77.71.156.41:4533/api/tracks/5/stream?q=original".toHttpUrl(), former, now)
        assertEquals("https://shelf-pc.example.ts.net/api/tracks/5/stream?q=original", moved.toString())
        // Anything else is left alone.
        assertNull(rebase("https://github.com/x".toHttpUrl(), former, now))
        assertNull(rebase("http://77.71.156.41:9999/api/ping".toHttpUrl(), former, now))
        assertNull(rebase("$secure/api/ping".toHttpUrl(), former, now))
    }
}
