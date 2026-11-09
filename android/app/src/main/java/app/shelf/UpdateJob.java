package app.shelf;

import android.app.job.JobParameters;
import android.app.job.JobService;

/** The six-hourly update check, run by Android in the background (see Updater). */
public class UpdateJob extends JobService {
    @Override
    public boolean onStartJob(final JobParameters params) {
        new Thread(new Runnable() {
            public void run() {
                Updater.check(getApplicationContext());
                jobFinished(params, false);
            }
        }, "shelf-update-job").start();
        return true;
    }

    @Override
    public boolean onStopJob(JobParameters params) {
        return true; // try again later
    }
}
