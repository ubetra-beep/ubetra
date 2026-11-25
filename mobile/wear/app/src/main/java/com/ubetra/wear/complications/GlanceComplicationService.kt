package com.ubetra.wear.complications

import android.app.PendingIntent
import android.content.Intent
import androidx.wear.watchface.complications.data.ComplicationData
import androidx.wear.watchface.complications.data.ComplicationType
import androidx.wear.watchface.complications.data.LongTextComplicationData
import androidx.wear.watchface.complications.data.PlainComplicationText
import androidx.wear.watchface.complications.data.ShortTextComplicationData
import androidx.wear.watchface.complications.datasource.ComplicationRequest
import androidx.wear.watchface.complications.datasource.SuspendingComplicationDataSourceService
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import com.ubetra.wear.GlanceText
import com.ubetra.wear.MainActivity
import com.ubetra.wear.WatchRepository
import com.ubetra.wear.WatchSummary
import com.ubetra.wear.cycleGlance
import com.ubetra.wear.lockGlance
import com.ubetra.wear.orgasmGlance
import com.ubetra.wear.sleepGlance

abstract class GlanceComplicationService : SuspendingComplicationDataSourceService() {
    protected abstract val requestCode: Int
    protected abstract fun glance(summary: WatchSummary): GlanceText
    protected abstract fun preview(): GlanceText

    override suspend fun onComplicationRequest(request: ComplicationRequest): ComplicationData? {
        return withContext(Dispatchers.IO) {
            val repo = WatchRepository.get(this@GlanceComplicationService)
            if (!repo.hasSession()) {
                return@withContext textData(request.complicationType, GlanceText("UBETRA", "Pair", "Pair the watch"))
            }
            val summary = try {
                repo.summary(force = false, timeoutMs = 8_000)
            } catch (_: Exception) {
                null
            } ?: return@withContext null
            textData(request.complicationType, glance(summary))
        }
    }

    override fun getPreviewData(type: ComplicationType): ComplicationData = textData(type, preview())

    private fun textData(type: ComplicationType, glance: GlanceText): ComplicationData {
        val description = PlainComplicationText.Builder("${glance.title}. ${glance.longText}").build()
        val tap = PendingIntent.getActivity(
            this,
            requestCode,
            Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        return when (type) {
            ComplicationType.LONG_TEXT -> LongTextComplicationData.Builder(
                PlainComplicationText.Builder(glance.longText).build(),
                description,
            )
                .setTitle(PlainComplicationText.Builder(glance.title).build())
                .setTapAction(tap)
                .build()
            else -> ShortTextComplicationData.Builder(
                PlainComplicationText.Builder(glance.shortText).build(),
                description,
            )
                .setTitle(PlainComplicationText.Builder(glance.title).build())
                .setTapAction(tap)
                .build()
        }
    }
}

class LockStatusComplicationService : GlanceComplicationService() {
    override val requestCode: Int = 11
    override fun glance(summary: WatchSummary): GlanceText = summary.lockGlance()
    override fun preview(): GlanceText = GlanceText("Locked", "2h 5m", "Locked for 2h 5m")
}

class SleepHoursComplicationService : GlanceComplicationService() {
    override val requestCode: Int = 12
    override fun glance(summary: WatchSummary): GlanceText = summary.sleepGlance()
    override fun preview(): GlanceText = GlanceText("Sleep", "7h 30m", "Last night 7h 30m")
}

class CycleDayComplicationService : GlanceComplicationService() {
    override val requestCode: Int = 13
    override fun glance(summary: WatchSummary): GlanceText = summary.cycleGlance()
    override fun preview(): GlanceText = GlanceText("Cycle", "Day 14", "Day 14")
}

class OrgasmLabelComplicationService : GlanceComplicationService() {
    override val requestCode: Int = 14
    override fun glance(summary: WatchSummary): GlanceText = summary.orgasmGlance()
    override fun preview(): GlanceText = GlanceText("7 days", "1", "1 in the last 7 days")
}
