package app.shelf

import android.app.job.JobParameters
import android.app.job.JobService
import app.shelf.update.Updater
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

/** The six-hourly update check, run by Android in the background. (The WebView app's class name, so its scheduled job carries over.) */
class UpdateJob : JobService() {
    private var job: Job? = null

    override fun onStartJob(params: JobParameters): Boolean {
        val app = application as ShelfApp
        job = CoroutineScope(Dispatchers.IO).launch {
            Updater(applicationContext, app.container.plainHttp).check(force = false)
            jobFinished(params, false)
        }
        return true
    }

    override fun onStopJob(params: JobParameters): Boolean { job?.cancel(); return true } // try again later
}
