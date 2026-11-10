package app.shelf.update

import android.Manifest
import android.app.job.JobScheduler
import android.content.pm.PackageManager
import androidx.test.core.app.ApplicationProvider
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
}
