package app.shelf.update

import android.Manifest
import android.app.job.JobScheduler
import android.content.pm.PackageManager
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class UpdateScheduleTest {
    /**
     * A fresh install (nothing scheduled by the WebView app before it) schedules the update check
     * at first launch. The check outlives restarts, which Android only allows with
     * RECEIVE_BOOT_COMPLETED; without it, JobScheduler throws and Shelf crashed on opening.
     */
    @Test fun freshInstallMaySchedulePersistedCheck() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val requested = context.packageManager
            .getPackageInfo(context.packageName, PackageManager.GET_PERMISSIONS).requestedPermissions.orEmpty()
        assertTrue("RECEIVE_BOOT_COMPLETED is needed for a persisted job",
            Manifest.permission.RECEIVE_BOOT_COMPLETED in requested)

        Updater.schedule(context)
        val job = context.getSystemService(JobScheduler::class.java).allPendingJobs.single { it.id == Updater.JOB }
        assertTrue(job.isPersisted)
    }

    /**
     * The background job asks GitHub even when Android runs it a little under 6 hours after the
     * last check; opening the app waits the full 6 hours.
     */
    @Test fun backgroundJobDoesNotSkipAnEarlyRun() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        context.getSharedPreferences("updates", android.content.Context.MODE_PRIVATE).edit()
            .putLong("checkedAt", System.currentTimeMillis() - 5 * 60 * 60 * 1000L).commit()
        var asked = 0
        val http = okhttp3.OkHttpClient.Builder().addInterceptor { chain ->
            asked++
            okhttp3.Response.Builder().request(chain.request()).protocol(okhttp3.Protocol.HTTP_1_1).code(503).message("busy")
                .body(okhttp3.ResponseBody.create(null, "")).build()
        }.build()
        val updater = Updater(context, http)
        kotlinx.coroutines.runBlocking {
            assertEquals(UpdateResult.UpToDate, updater.check(force = false))  // on opening: 5 h is too soon
            assertEquals(0, asked)
            updater.check(force = false, gap = Updater.JOB_GAP)  // the background job: it asks
            assertEquals(1, asked)
        }
    }
}
