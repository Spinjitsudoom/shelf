package app.shelf.playback

import org.junit.Assert.assertEquals
import org.junit.Test

class PartySyncTest {
    private val host = Here(trackId = 7, positionS = 60.0, playing = true)

    @Test fun anotherSongLoadsTheHostsAtTheirPlace() =
        assertEquals(Step(load = true, seekTo = 60.0, play = true), follow(Here(3, 10.0, true), host))

    @Test fun nothingPlayingHereStartsIt() =
        assertEquals(Step(load = true, seekTo = 60.0, play = true), follow(Here(null, 0.0, false), host))

    @Test fun closeEnoughIsLeftAlone() = assertEquals(Step(), follow(Here(7, 61.5, true), host))

    @Test fun driftSeeks() = assertEquals(Step(seekTo = 60.0), follow(Here(7, 64.0, true), host))

    @Test fun pauseAndPlayFollowTheHost() {
        assertEquals(Step(play = false), follow(Here(7, 60.0, true), host.copy(playing = false)))
        assertEquals(Step(play = true), follow(Here(7, 60.0, false), host))
    }

    @Test fun hostStoppedPausesHere() {
        assertEquals(Step(play = false), follow(Here(7, 60.0, true), Here(null, 0.0, false)))
        assertEquals(Step(), follow(Here(7, 60.0, false), Here(null, 0.0, false)))
    }
}
