package app.shelf.connect

import android.os.Looper
import androidx.media3.common.DeviceInfo as MediaDeviceInfo
import androidx.media3.common.Player
import androidx.test.ext.junit.runners.AndroidJUnit4
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class RemotePlayerTest {
    private val link = FakeLink(remoteUi(now = 1000))
    private val player = RemotePlayer(Looper.getMainLooper(), link, { null }, clock = { 1000 })

    @Test fun stateMapsToPlayer() {
        assertEquals(3, player.mediaItemCount)
        assertEquals(1, player.currentMediaItemIndex)
        assertEquals(30_000L, player.currentPosition)
        assertTrue(player.isPlaying)
        assertTrue(player.shuffleModeEnabled)
        assertEquals(Player.REPEAT_MODE_ALL, player.repeatMode)
        assertEquals("Song 2", player.currentMediaItem!!.mediaMetadata.title)
    }

    @Test fun playPauseSendCmds() {
        player.pause()
        assertEquals("pause", link.cmds.last().first)
        assertTrue("shown paused straight away", !player.isPlaying)
        player.play()
        assertEquals("play", link.cmds.last().first)
    }

    @Test fun seekNextPrevJumpMapping() {
        player.seekToNextMediaItem(); assertEquals("next", link.cmds.last().first)
        player.seekToPreviousMediaItem(); assertEquals("prev", link.cmds.last().first)
        player.seekToPrevious(); assertEquals("prev", link.cmds.last().first)
        player.seekTo(60_000); assertEquals("seek" to listOf(JsonPrimitive(60.0)), link.cmds.last())
        player.seekTo(2, 0); assertEquals("jumpTo" to listOf(JsonPrimitive(2)), link.cmds.last())
    }

    @Test fun moveSendsMoveItem() {
        player.moveMediaItem(2, 1) // song 2 is playing and song 3 is the only one up next: nowhere to go
        player.moveMediaItem(1, 2)
        assertTrue("the playing song isn't moved", link.cmds.none { it.first == "moveItem" })
        val wide = FakeLink(remoteUi(now = 1000).let { u -> u.copy(queue = listOf(tr(1), tr(2), tr(3), tr(4), tr(5))) })
        val p = RemotePlayer(Looper.getMainLooper(), wide, { null }, clock = { 1000 })
        p.moveMediaItem(4, 2)
        assertEquals("moveItem" to listOf(JsonPrimitive(4), JsonPrimitive(2)), wide.cmds.last())
        assertEquals("shown moved straight away", listOf("Song 1", "Song 2", "Song 5", "Song 3", "Song 4"),
            (0 until p.mediaItemCount).map { p.getMediaItemAt(it).mediaMetadata.title.toString() })
    }

    @Test fun volumeGoesToRemote() {
        assertEquals(MediaDeviceInfo.PLAYBACK_TYPE_REMOTE, player.deviceInfo.playbackType)
        assertEquals(50, player.deviceVolume)
        player.setDeviceVolume(40, 0)
        assertEquals("setVolume" to listOf(JsonPrimitive(0.4)), link.cmds.last())
        assertEquals(40, player.deviceVolume)
    }
}
