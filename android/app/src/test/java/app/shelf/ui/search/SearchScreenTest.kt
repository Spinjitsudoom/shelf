package app.shelf.ui.search

import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import androidx.test.ext.junit.runners.AndroidJUnit4
import app.shelf.data.ShelfApi
import app.shelf.data.Track
import app.shelf.playback.PlayContext
import app.shelf.ui.theme.ShelfTheme
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class SearchScreenTest {
    @get:Rule val rule = createComposeRule()

    /** A server in memory that answers every search with three songs. */
    private val api = ShelfApi("http://shelf.test/".toHttpUrl(), { "token" }, OkHttpClient.Builder().addInterceptor { chain ->
        val songs = listOf("Ocean Eyes", "Ocean Drive", "Oceans").mapIndexed { i, t ->
            """{"id":${i + 1},"title":"$t","artist":"Band $i","album":"Album $i","albumId":${i + 1},"duration":200}"""
        }
        Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1).code(200).message("OK")
            .body("""{"tracks":[${songs.joinToString(",")}]}""".toResponseBody("application/json".toMediaType())).build()
    }.build())

    /** A song from search plays on its own, so Autoplay carries on with similar songs, not the other results. */
    @Test fun searchedSongPlaysOnItsOwn() {
        var played: Triple<List<Track>, Int, PlayContext>? = null
        rule.setContent { ShelfTheme { SearchScreen(api, { t, i, c -> played = Triple(t, i, c) }, {}, {}) } }
        rule.onNode(hasSetTextAction()).performTextInput("ocean")
        rule.waitUntil(5000) { rule.onAllNodes(hasText("Ocean Drive")).fetchSemanticsNodes().isNotEmpty() }
        rule.onNodeWithText("Ocean Drive").performClick()
        assertEquals(listOf("Ocean Drive"), played!!.first.map { it.title })
        assertEquals(0, played!!.second)
        assertEquals("Search: ocean", played!!.third.label)
    }
}
