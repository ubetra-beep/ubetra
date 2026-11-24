package com.ubetra.wear.tiles

import android.content.Context
import android.content.Intent
import androidx.concurrent.futures.CallbackToFutureAdapter
import androidx.wear.protolayout.ActionBuilders
import androidx.wear.protolayout.ColorBuilders.argb
import androidx.wear.protolayout.DeviceParametersBuilders.DeviceParameters
import androidx.wear.protolayout.DimensionBuilders.dp
import androidx.wear.protolayout.DimensionBuilders.expand
import androidx.wear.protolayout.LayoutElementBuilders.Box
import androidx.wear.protolayout.LayoutElementBuilders.Column
import androidx.wear.protolayout.LayoutElementBuilders.LayoutElement
import androidx.wear.protolayout.LayoutElementBuilders.Spacer
import androidx.wear.protolayout.ModifiersBuilders.Clickable
import androidx.wear.protolayout.ModifiersBuilders.Modifiers
import androidx.wear.protolayout.ModifiersBuilders.Padding
import androidx.wear.protolayout.ResourceBuilders.Resources
import androidx.wear.protolayout.TimelineBuilders.Timeline
import androidx.wear.protolayout.material.Colors
import androidx.wear.protolayout.material.CompactChip
import androidx.wear.protolayout.material.Text
import androidx.wear.protolayout.material.Typography
import androidx.wear.tiles.RequestBuilders
import androidx.wear.tiles.TileBuilders
import androidx.wear.tiles.TileService
import com.google.common.util.concurrent.ListenableFuture
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import com.ubetra.wear.EXTRA_BANNER
import com.ubetra.wear.FINISH_ON_PHONE
import com.ubetra.wear.FINISH_ON_PHONE_CONFLICT
import com.ubetra.wear.MainActivity
import com.ubetra.wear.WatchAction
import com.ubetra.wear.WatchRepository
import com.ubetra.wear.WatchSummary

private const val RESOURCE_VERSION = "1"
private const val TILE_PREFS = "ubetra_wear_tiles"
private const val MAX_CHIPS = 4

abstract class UbetraTileService : TileService() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    protected abstract val tileKey: String

    protected abstract fun title(): String

    protected abstract fun lines(summary: WatchSummary): List<String>

    protected abstract fun actions(summary: WatchSummary): List<WatchAction>

    override fun onTileRequest(
        requestParams: RequestBuilders.TileRequest,
    ): ListenableFuture<TileBuilders.Tile> {
        return CallbackToFutureAdapter.getFuture { completer ->
            scope.launch {
                try {
                    completer.set(renderTile(requestParams))
                } catch (error: Throwable) {
                    completer.setException(error)
                }
            }
            tileKey
        }
    }

    override fun onTileResourcesRequest(
        requestParams: RequestBuilders.ResourcesRequest,
    ): ListenableFuture<Resources> {
        return CallbackToFutureAdapter.getFuture { completer ->
            completer.set(Resources.Builder().setVersion(RESOURCE_VERSION).build())
            "resources"
        }
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    private fun renderTile(request: RequestBuilders.TileRequest): TileBuilders.Tile {
        val root = try {
            val notice = handleClick(request.currentState.lastClickableId.orEmpty())
            val summary = runCatching {
                WatchRepository.get(this).summary(force = false, timeoutMs = 8_000)
            }.getOrNull()
            layout(request.deviceConfiguration, summary, notice)
        } catch (error: Exception) {
            messageLayout(request.deviceConfiguration, title(), error.message ?: "Could not load")
        }
        return TileBuilders.Tile.Builder()
            .setResourcesVersion(RESOURCE_VERSION)
            .setFreshnessIntervalMillis(5 * 60 * 1000L)
            .setTileTimeline(Timeline.fromLayoutElement(root))
            .build()
    }

    private fun handleClick(clickId: String): String {
        val saved = peekNotice()
        if (clickId.isBlank() || !consumeClick(clickId)) return saved
        val summary = runCatching {
            WatchRepository.get(this).summary(force = false, timeoutMs = 8_000)
        }.getOrNull() ?: return saved
        val action = summary.actions.firstOrNull { it.key == clickId } ?: return saved
        if (action.finishOnPhone) {
            openBanner(FINISH_ON_PHONE)
            return rememberNotice(FINISH_ON_PHONE)
        }
        val outcome = try {
            WatchRepository.get(this).perform(action, timeoutMs = 8_000)
        } catch (error: Exception) {
            return rememberNotice(error.message ?: "Could not send")
        }
        if (outcome.text == FINISH_ON_PHONE || outcome.text == FINISH_ON_PHONE_CONFLICT) {
            openBanner(outcome.text)
        }
        if (outcome.refreshSummary) {
            runCatching { WatchRepository.get(this).summary(force = true, timeoutMs = 8_000) }
        }
        return rememberNotice(outcome.text)
    }

    private fun layout(
        device: DeviceParameters,
        summary: WatchSummary?,
        notice: String,
    ): LayoutElement {
        if (summary == null) {
            return messageLayout(
                device,
                title(),
                if (WatchRepository.get(this).hasSession()) "Open phone" else "Pair on the watch",
                openChip = true,
            )
        }
        val column = Column.Builder().setWidth(expand())
        column.addContent(line(title(), Typography.TYPOGRAPHY_TITLE3, 1))
        if (notice.isNotBlank()) {
            column.addContent(gap())
            column.addContent(line(notice, Typography.TYPOGRAPHY_CAPTION1, 2))
        }
        lines(summary).take(3).forEach { text ->
            column.addContent(gap())
            column.addContent(line(text, Typography.TYPOGRAPHY_BODY2, 2))
        }
        val shown = visibleActions(summary)
        shown.forEach { action ->
            column.addContent(gap())
            val clickable = if (action.finishOnPhone) {
                launchClick(action.key, FINISH_ON_PHONE)
            } else {
                loadClick(action.key)
            }
            column.addContent(chip(device, action.label, clickable))
        }
        val hidden = actions(summary).size - shown.size
        if (hidden > 0) {
            column.addContent(gap())
            column.addContent(chip(device, "More", launchClick("more", null)))
        }
        return padded(column.build())
    }

    private fun visibleActions(summary: WatchSummary): List<WatchAction> {
        val all = actions(summary)
        return if (all.size <= MAX_CHIPS) all else all.take(MAX_CHIPS - 1)
    }

    private fun messageLayout(
        device: DeviceParameters,
        title: String,
        message: String,
        openChip: Boolean = false,
    ): LayoutElement {
        val column = Column.Builder().setWidth(expand())
        column.addContent(line(title, Typography.TYPOGRAPHY_TITLE3, 1))
        column.addContent(gap())
        column.addContent(line(message, Typography.TYPOGRAPHY_BODY2, 3))
        if (openChip) {
            column.addContent(gap())
            column.addContent(chip(device, "Open", launchClick("open", null)))
        }
        return padded(column.build())
    }

    private fun line(text: String, typography: Int, maxLines: Int): LayoutElement {
        return Text.Builder(this, text.ifBlank { "—" })
            .setTypography(typography)
            .setColor(argb(Colors.DEFAULT.onSurface))
            .setMaxLines(maxLines)
            .build()
    }

    private fun chip(device: DeviceParameters, label: String, clickable: Clickable): LayoutElement {
        val text = label.trim().ifBlank { "Action" }.let { if (it.length <= 32) it else it.take(31) + "…" }
        return CompactChip.Builder(this, text, clickable, device).build()
    }

    private fun gap(): LayoutElement = Spacer.Builder().setWidth(expand()).setHeight(dp(4f)).build()

    private fun padded(content: LayoutElement): LayoutElement {
        return Box.Builder()
            .setWidth(expand())
            .setHeight(expand())
            .setModifiers(
                Modifiers.Builder()
                    .setPadding(Padding.Builder().setAll(dp(6f)).build())
                    .build(),
            )
            .addContent(content)
            .build()
    }

    private fun loadClick(id: String): Clickable {
        return Clickable.Builder()
            .setId(id)
            .setOnClick(ActionBuilders.LoadAction.Builder().build())
            .build()
    }

    private fun launchClick(id: String, banner: String?): Clickable {
        val activity = ActionBuilders.AndroidActivity.Builder()
            .setPackageName(packageName)
            .setClassName(MainActivity::class.java.name)
        if (!banner.isNullOrBlank()) {
            activity.addKeyToExtraMapping(
                EXTRA_BANNER,
                ActionBuilders.AndroidStringExtra.Builder().setValue(banner).build(),
            )
        }
        return Clickable.Builder()
            .setId(id)
            .setOnClick(
                ActionBuilders.LaunchAction.Builder()
                    .setAndroidActivity(activity.build())
                    .build(),
            )
            .build()
    }

    private fun openBanner(message: String) {
        val intent = Intent(this, MainActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            putExtra(EXTRA_BANNER, message)
        }
        try {
            startActivity(intent)
        } catch (_: Exception) {
            // The tile keeps the same sentence when the activity cannot open.
        }
    }

    private fun consumeClick(clickId: String): Boolean {
        val prefs = getSharedPreferences(TILE_PREFS, Context.MODE_PRIVATE)
        val last = prefs.getString("last.$tileKey", "").orEmpty()
        if (clickId.isBlank()) {
            prefs.edit().putBoolean("armed.$tileKey", true).commit()
            return false
        }
        val armed = prefs.getBoolean("armed.$tileKey", true)
        val now = System.currentTimeMillis()
        if (!armed && clickId == last) return false
        if (clickId == last && now - prefs.getLong("lastAt.$tileKey", 0L) < 2_500L) return false
        prefs.edit()
            .putString("last.$tileKey", clickId)
            .putLong("lastAt.$tileKey", now)
            .putBoolean("armed.$tileKey", false)
            .commit()
        return true
    }

    private fun peekNotice(): String {
        val prefs = getSharedPreferences(TILE_PREFS, Context.MODE_PRIVATE)
        val at = prefs.getLong("notice.$tileKey.at", 0L)
        if (System.currentTimeMillis() - at > 60_000L) return ""
        return prefs.getString("notice.$tileKey", "").orEmpty()
    }

    private fun rememberNotice(message: String): String {
        getSharedPreferences(TILE_PREFS, Context.MODE_PRIVATE)
            .edit()
            .putString("notice.$tileKey", message)
            .putLong("notice.$tileKey.at", System.currentTimeMillis())
            .commit()
        return message
    }
}

class ChastityStatusTileService : UbetraTileService() {
    override val tileKey: String = "status"
    override fun title(): String = "Chastity"
    override fun actions(summary: WatchSummary): List<WatchAction> = emptyList()
    override fun lines(summary: WatchSummary): List<String> {
        val lines = mutableListOf(summary.chastitySummary.ifBlank { "No chastity status" })
        if (summary.subjects.any { it.timerOverdue }) lines += "Overdue"
        val breakLabel = summary.subjects.mapNotNull { it.breakLabel }.distinct().joinToString(" · ")
        if (breakLabel.isNotBlank()) lines += breakLabel
        return lines
    }
}

class QuickLockTileService : UbetraTileService() {
    override val tileKey: String = "lock"
    override fun title(): String = "Quick lock"
    override fun actions(summary: WatchSummary): List<WatchAction> = summary.lockActions()
    override fun lines(summary: WatchSummary): List<String> {
        if (summary.lockActions().isEmpty()) return listOf("No lock actions")
        return listOf(summary.chastitySummary.ifBlank { "Lock" })
    }
}

class QuickLogTileService : UbetraTileService() {
    override val tileKey: String = "log"
    override fun title(): String = "Quick log"
    override fun actions(summary: WatchSummary): List<WatchAction> = summary.logActions()
    override fun lines(summary: WatchSummary): List<String> {
        if (summary.logActions().isEmpty()) return listOf("No log actions")
        val label = summary.orgasmLabel.ifBlank { "Log now" }
        return listOf(label)
    }
}
