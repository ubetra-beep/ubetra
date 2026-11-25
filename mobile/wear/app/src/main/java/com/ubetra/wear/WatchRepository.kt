package com.ubetra.wear

import android.content.ComponentName
import android.content.Context
import androidx.wear.tiles.TileService
import androidx.wear.watchface.complications.datasource.ComplicationDataSourceUpdateRequester
import com.ubetra.wear.complications.CycleDayComplicationService
import com.ubetra.wear.complications.LockStatusComplicationService
import com.ubetra.wear.complications.OrgasmLabelComplicationService
import com.ubetra.wear.complications.SleepHoursComplicationService
import com.ubetra.wear.tiles.ChastityStatusTileService
import com.ubetra.wear.tiles.QuickLockTileService
import com.ubetra.wear.tiles.QuickLogTileService
import kotlinx.coroutines.runBlocking
import org.json.JSONObject

class WatchRepository private constructor(context: Context) {
    private val appContext = context.applicationContext
    private val store = WatchSessionStore(appContext)

    fun hasSession(): Boolean = store.isPaired()

    fun pair(code: String) = runBlocking {
        val normalized = normalizePairCode(code)
        if (normalized.length != 8) throw WatchApiException(400, "Enter the 8-character code")
        val reply = PhoneRelay.pair(appContext, normalized, 20_000)
        if (reply.optString("type") != "pair_ok") {
            throw WatchApiException(400, reply.optString("text").ifBlank { "Pairing failed" })
        }
        val key = android.util.Base64.decode(reply.getString("key"), android.util.Base64.NO_WRAP)
        store.saveKey(key)
        store.clearSummary()
    }

    fun forget() {
        store.clear()
    }

    fun summary(force: Boolean, timeoutMs: Int = 20_000): WatchSummary {
        val cached = readCached()
        if (!force && cached != null && System.currentTimeMillis() - cached.second < SUMMARY_CACHE_MS) {
            return cached.first
        }
        if (!store.isPaired()) throw WatchSignedOutException()
        return try {
            val json = runBlocking { PhoneRelay.summary(appContext, timeoutMs.toLong()) }
            store.writeSummary(json.toString())
            parseSummary(json)
        } catch (err: WatchSignedOutException) {
            throw err
        } catch (err: Exception) {
            if (cached != null) return cached.first
            if (err is WatchApiException) throw err
            throw WatchApiException(0, err.message ?: OPEN_PHONE)
        }
    }

    fun perform(action: WatchAction, timeoutMs: Int = 8_000): ActionOutcome {
        if (action.finishOnPhone) return ActionOutcome(FINISH_ON_PHONE, refreshSummary = false)
        if (!store.isPaired()) throw WatchSignedOutException()
        val reply = try {
            runBlocking { PhoneRelay.action(appContext, action, timeoutMs.toLong()) }
        } catch (err: Exception) {
            if (err is WatchApiException) throw err
            throw WatchApiException(0, err.message ?: OPEN_PHONE)
        }
        val summary = reply.optJSONObject("summary")
        if (summary != null) store.writeSummary(summary.toString())
        val text = reply.optString("text").ifBlank { if (reply.optBoolean("ok")) "Done" else OPEN_PHONE }
        return ActionOutcome(text, refreshSummary = summary == null && reply.optBoolean("ok"))
    }

    fun pushSurfaces() {
        val updater = TileService.getUpdater(appContext)
        updater.requestUpdate(ChastityStatusTileService::class.java)
        updater.requestUpdate(QuickLockTileService::class.java)
        updater.requestUpdate(QuickLogTileService::class.java)
        listOf(
            LockStatusComplicationService::class.java,
            SleepHoursComplicationService::class.java,
            CycleDayComplicationService::class.java,
            OrgasmLabelComplicationService::class.java,
        ).forEach { service ->
            ComplicationDataSourceUpdateRequester.create(
                appContext,
                ComponentName(appContext, service),
            ).requestUpdateAll()
        }
    }

    private fun readCached(): Pair<WatchSummary, Long>? {
        val stored = store.readSummary() ?: return null
        return try {
            parseSummary(JSONObject(stored.first)) to stored.second
        } catch (_: Exception) {
            null
        }
    }

    companion object {
        private const val SUMMARY_CACHE_MS = 60_000L

        @Volatile
        private var instance: WatchRepository? = null

        fun get(context: Context): WatchRepository {
            return instance ?: synchronized(this) {
                instance ?: WatchRepository(context.applicationContext).also { instance = it }
            }
        }
    }
}
