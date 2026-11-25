package com.ubetra.localstore

import android.content.Context
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import java.util.concurrent.TimeUnit

class SyncWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result {
        val engine = SyncEngine(applicationContext)
        if (!engine.configured()) return Result.success()
        return try {
            if (!engine.probe()) return Result.retry()
            engine.pushPull()
            Result.success()
        } catch (_: Exception) {
            Result.retry()
        }
    }
}

object SyncScheduler {
    fun ensure(context: Context) {
        val constraints = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()
        val periodic = PeriodicWorkRequestBuilder<SyncWorker>(15, TimeUnit.MINUTES)
            .setConstraints(constraints)
            .build()
        WorkManager.getInstance(context).enqueueUniquePeriodicWork(
            "ubetra-sync",
            ExistingPeriodicWorkPolicy.UPDATE,
            periodic,
        )
    }

    fun enqueueSoon(context: Context) {
        val once = OneTimeWorkRequestBuilder<SyncWorker>().build()
        WorkManager.getInstance(context).enqueueUniqueWork(
            "ubetra-sync-now",
            ExistingWorkPolicy.REPLACE,
            once,
        )
    }
}
