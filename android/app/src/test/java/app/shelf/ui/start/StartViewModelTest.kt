package app.shelf.ui.start

import android.content.Context
import android.os.Looper
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import app.shelf.data.ServerStore
import app.shelf.data.ShelfApi
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Shadows.shadowOf
import java.net.InetAddress

@RunWith(AndroidJUnit4::class)
class StartViewModelTest {
    private val server = MockWebServer()
    private lateinit var store: ServerStore
    private lateinit var vm: StartViewModel
    private lateinit var host: String

    @Before fun setUp() {
        server.start(InetAddress.getByName("127.0.0.1"), 0)
        host = "127.0.0.1:${server.port}"
        val prefs = ApplicationProvider.getApplicationContext<Context>().getSharedPreferences("t", Context.MODE_PRIVATE)
        prefs.edit().clear().commit()
        store = ServerStore(prefs)
        vm = StartViewModel(store) { url -> ShelfApi("$url/".toHttpUrl(), { store.token }, OkHttpClient()) }
    }

    @After fun tearDown() = server.close()

    private fun respond(body: String, code: Int = 200) =
        server.enqueue(MockResponse.Builder().code(code).addHeader("Content-Type", "application/json").body(body).build())

    /** Let the view model's work finish (it talks to the network on another thread). */
    private fun settle() {
        val end = System.currentTimeMillis() + 5000
        do { shadowOf(Looper.getMainLooper()).idle(); Thread.sleep(10) } while (vm.state.value.busy && System.currentTimeMillis() < end)
        shadowOf(Looper.getMainLooper()).idle()
    }

    private val ping = """{"app":"shelf","version":"0.6.0"}"""

    @Test fun badAddressShowsHint() {
        vm.submitServer("ftp://x"); settle()
        assertEquals("That doesn’t look like a server address. Try something like 192.168.1.20:4533.", vm.state.value.error)
        assertEquals(StartViewModel.Step.Server, vm.state.value.step)
    }

    @Test fun unreachableServerMessage() {
        server.close()
        vm.submitServer(host); settle()
        assertEquals("Couldn’t reach $host. Check the server is running and this phone is on the same network.", vm.state.value.error)
    }

    @Test fun notShelfMessage() {
        respond("""{"app":"nope"}""")
        vm.submitServer(host); settle()
        assertEquals("$host answered, but it isn’t a Shelf server.", vm.state.value.error)
    }

    @Test fun setupNeededMessage() {
        respond(ping); respond("""{"setup":true,"signedIn":false}""")
        vm.submitServer(host); settle()
        assertEquals("This server has no accounts yet. Open it in a browser to create the admin account.", vm.state.value.error)
    }

    @Test fun serverOkGoesToSignIn() {
        respond(ping); respond("""{"setup":false,"signedIn":false}""")
        vm.submitServer(host); settle()
        assertEquals(StartViewModel.Step.SignIn, vm.state.value.step)
        assertNull(vm.state.value.error)
        assertEquals("http://$host", store.server)
    }

    @Test fun wrongPasswordMessage() {
        store.server = "http://$host"
        respond("""{"detail":"Wrong username or password"}""", 401)
        vm.signIn("Listener", "nope"); settle()
        assertEquals("Wrong username or password.", vm.state.value.error)
        assertNull(store.token)
    }

    @Test fun lockedOutMessage() {
        store.server = "http://$host"
        respond("""{"detail":"Too many attempts. Try again in a few minutes."}""", 429)
        vm.signIn("Listener", "x"); settle()
        assertEquals("Too many attempts. Try again in a few minutes.", vm.state.value.error)
    }

    @Test fun signInStoresTokenAndFinishes() {
        store.server = "http://$host"
        respond("""{"ok":true,"user":{"id":2,"username":"Listener","admin":true},"token":"tok"}""")
        vm.signIn("Listener", "pw"); settle()
        assertEquals(StartViewModel.Step.Done, vm.state.value.step)
        assertEquals("tok", store.token)
        assertEquals("Listener", store.username)
    }

    @Test fun expiredTokenGoesToSignIn() {
        store.server = "http://$host"; store.token = "old"
        respond("""{"setup":false,"signedIn":false}""")
        vm.start(); settle()
        assertEquals(StartViewModel.Step.SignIn, vm.state.value.step)
        assertEquals("http://$host", store.server)
        assertNull(store.token)
    }

    @Test fun offlineWithTokenStillOpens() {
        store.server = "http://$host"; store.token = "tok"
        server.close()
        vm.start(); settle()
        assertEquals(StartViewModel.Step.Done, vm.state.value.step)
    }

    @Test fun noServerAsksForOne() {
        vm.start(); settle()
        assertEquals(StartViewModel.Step.Server, vm.state.value.step)
    }

    @Test fun upgradeNoteAfterWebViewApp() {
        // The WebView app saved the server (same key) but its sign-in lived in the web page.
        store.server = "http://$host"
        vm = StartViewModel(store) { url -> ShelfApi("$url/".toHttpUrl(), { store.token }, OkHttpClient()) }
        vm.start()
        settle()
        assertEquals(StartViewModel.Step.SignIn, vm.state.value.step)
        assertEquals("Shelf has a new look. Sign in once more. Anything downloaded in the old app needs downloading again.", vm.state.value.note)
    }

    @Test fun noUpgradeNoteOnFreshInstall() {
        vm.start()
        settle()
        assertNull(vm.state.value.note)
        // Signed out on purpose after signing in here: no note either.
        store.server = "http://$host"
        store.native = true
        vm = StartViewModel(store) { url -> ShelfApi("$url/".toHttpUrl(), { store.token }, OkHttpClient()) }
        vm.start()
        settle()
        assertNull(vm.state.value.note)
    }
}
