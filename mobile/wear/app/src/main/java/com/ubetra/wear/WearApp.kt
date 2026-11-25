package com.ubetra.wear

import android.app.RemoteInput
import android.content.ActivityNotFoundException
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.wear.compose.foundation.lazy.ScalingLazyColumn
import androidx.wear.compose.foundation.lazy.ScalingLazyListScope
import androidx.wear.compose.foundation.lazy.rememberScalingLazyListState
import androidx.wear.compose.material.Chip
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.PositionIndicator
import androidx.wear.compose.material.Scaffold
import androidx.wear.compose.material.Text
import androidx.wear.compose.material.TimeText
import androidx.wear.input.RemoteInputIntentHelper
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

private const val KEY_CODE = "pair_code"

private sealed interface Screen {
    data object Loading : Screen
    data object Pair : Screen
    data object Letters : Screen
    data object Home : Screen
    data class Notice(val message: String) : Screen
}

@Composable
fun WearApp(banner: String?, bannerId: Long = 0L) {
    val context = LocalContext.current
    val repo = remember { WatchRepository.get(context) }
    val scope = rememberCoroutineScope()
    var screen by remember { mutableStateOf<Screen>(Screen.Loading) }
    var code by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    var bannerText by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    var summary by remember { mutableStateOf<WatchSummary?>(null) }

    val codeLauncher = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        val entered = result.data?.let { RemoteInput.getResultsFromIntent(it) }
            ?.getCharSequence(KEY_CODE)
            ?.toString()
            .orEmpty()
        if (entered.isNotBlank()) code = normalizePairCode(entered).take(8)
    }

    fun launchCode() {
        val remote = RemoteInput.Builder(KEY_CODE).setLabel("Pairing code").build()
        val intent = RemoteInputIntentHelper.createActionRemoteInputIntent()
        RemoteInputIntentHelper.putRemoteInputsExtra(intent, listOf(remote))
        RemoteInputIntentHelper.putTitleExtra(intent, "Pairing code")
        RemoteInputIntentHelper.putConfirmLabelExtra(intent, "OK")
        try {
            codeLauncher.launch(intent)
        } catch (_: ActivityNotFoundException) {
            error = "Keyboard is unavailable. Use Tap letters."
            screen = Screen.Letters
        }
    }

    suspend fun loadHome() {
        try {
            summary = withContext(Dispatchers.IO) { repo.summary(force = true) }
            withContext(Dispatchers.IO) { runCatching { repo.pushSurfaces() } }
            screen = Screen.Home
            error = null
        } catch (err: WatchSignedOutException) {
            screen = Screen.Pair
            error = err.message
        } catch (err: Exception) {
            error = err.message ?: OPEN_PHONE
            val cached = runCatching { repo.summary(force = false) }.getOrNull()
            if (cached != null) {
                summary = cached
                screen = Screen.Home
            } else if (screen is Screen.Loading) {
                screen = if (repo.hasSession()) Screen.Home else Screen.Pair
            }
        }
    }

    fun runAction(action: WatchAction) {
        if (action.finishOnPhone) {
            screen = Screen.Notice(FINISH_ON_PHONE)
            return
        }
        scope.launch {
            busy = true
            try {
                val outcome = withContext(Dispatchers.IO) { repo.perform(action) }
                bannerText = outcome.text
                if (outcome.text == OPEN_PHONE) {
                    screen = Screen.Notice(OPEN_PHONE)
                } else if (outcome.refreshSummary) {
                    summary = withContext(Dispatchers.IO) { repo.summary(force = true) }
                    withContext(Dispatchers.IO) { runCatching { repo.pushSurfaces() } }
                } else {
                    summary = withContext(Dispatchers.IO) { runCatching { repo.summary(force = false) }.getOrNull() } ?: summary
                }
            } catch (err: WatchSignedOutException) {
                screen = Screen.Pair
                error = err.message
            } catch (err: Exception) {
                val message = err.message ?: OPEN_PHONE
                bannerText = message
                if (message == OPEN_PHONE) screen = Screen.Notice(OPEN_PHONE)
            } finally {
                busy = false
            }
        }
    }

    LaunchedEffect(Unit) {
        val paired = withContext(Dispatchers.IO) { runCatching { repo.hasSession() }.getOrDefault(false) }
        if (!paired) {
            screen = Screen.Pair
            return@LaunchedEffect
        }
        if (!banner.isNullOrBlank()) {
            screen = Screen.Notice(banner)
            return@LaunchedEffect
        }
        loadHome()
    }

    LaunchedEffect(bannerId) {
        if (!banner.isNullOrBlank() && bannerId != 0L && screen !is Screen.Loading) {
            val paired = withContext(Dispatchers.IO) { runCatching { repo.hasSession() }.getOrDefault(false) }
            if (paired) screen = Screen.Notice(banner)
        }
    }

    LaunchedEffect(screen) {
        if (screen !is Screen.Home) return@LaunchedEffect
        while (true) {
            delay(60_000)
            try {
                summary = withContext(Dispatchers.IO) { repo.summary(force = true) }
                withContext(Dispatchers.IO) { runCatching { repo.pushSurfaces() } }
            } catch (err: WatchSignedOutException) {
                screen = Screen.Pair
                error = err.message
                return@LaunchedEffect
            } catch (err: Exception) {
                error = err.message
            }
        }
    }

    when (val current = screen) {
        Screen.Loading -> WearPage {
            item { Title("UBETRA") }
            item { Body("Loading") }
        }
        Screen.Pair -> WearPage {
            item { Title("Pair with phone") }
            item { Body("Open UBETRA on the phone and enter this code. The watch does not use a server address.") }
            item { Body(if (code.isBlank()) "8-character code" else formatPairCode(code)) }
            error?.let { message -> item { Body(message) } }
            item { ActionChip("Keyboard", !busy) { launchCode() } }
            item { ActionChip("Tap letters", !busy) { screen = Screen.Letters } }
            if (normalizePairCode(code).length == 8) {
                item {
                    ActionChip(if (busy) "Pairing…" else "Pair", !busy) {
                        scope.launch {
                            busy = true
                            error = null
                            try {
                                withContext(Dispatchers.IO) { repo.pair(code) }
                                loadHome()
                            } catch (err: Exception) {
                                error = err.message ?: "Pairing failed"
                            } finally {
                                busy = false
                            }
                        }
                    }
                }
            }
        }
        Screen.Letters -> WearPage {
            item { Title(formatPairCode(code).ifBlank { "Code" }) }
            item { ActionChip("Delete", code.isNotEmpty()) { code = code.dropLast(1) } }
            item { ActionChip("Done", true) { screen = Screen.Pair } }
            PAIR_ALPHABET.forEach { letter ->
                item {
                    ActionChip(letter.toString(), code.length < 8) {
                        if (code.length < 8) code += letter
                    }
                }
            }
        }
        Screen.Home -> WearPage {
            val currentSummary = summary
            item { Title(currentSummary?.displayName?.ifBlank { "UBETRA" } ?: "UBETRA") }
            error?.let { message -> item { Body(message) } }
            bannerText?.let { message -> item { Body(message) } }
            if (currentSummary == null) {
                item { Body(OPEN_PHONE) }
                item {
                    ActionChip("Refresh", !busy) {
                        scope.launch {
                            busy = true
                            try {
                                loadHome()
                            } finally {
                                busy = false
                            }
                        }
                    }
                }
            } else {
                item { Body(currentSummary.chastitySummary.ifBlank { "Chastity is off" }) }
                currentSummary.sleepGlance().takeIf { currentSummary.sleepEnabled && it.shortText != "—" }
                    ?.let { item { Body("Sleep ${it.shortText}") } }
                currentSummary.cycleGlance().takeIf { currentSummary.cycleEnabled && it.shortText != "—" && it.shortText != "Off" }
                    ?.let { item { Body("Cycle ${it.shortText}") } }
                if (currentSummary.orgasmEnabled && currentSummary.orgasmLabel.isNotBlank()) {
                    item { Body(currentSummary.orgasmLabel) }
                }
                val lockActions = currentSummary.lockActions()
                if (lockActions.isNotEmpty()) item { Body("Lock") }
                lockActions.forEach { action ->
                    item { ActionChip(action.label, !busy) { runAction(action) } }
                }
                val logActions = currentSummary.logActions()
                if (logActions.isNotEmpty()) item { Body("Log") }
                logActions.forEach { action ->
                    item { ActionChip(action.label, !busy) { runAction(action) } }
                }
            }
            item {
                ActionChip("Unpair", !busy) {
                    scope.launch {
                        withContext(Dispatchers.IO) { runCatching { repo.forget() } }
                        summary = null
                        code = ""
                        bannerText = null
                        screen = Screen.Pair
                    }
                }
            }
        }
        is Screen.Notice -> WearPage {
            item { Title(current.message) }
            item { Body(if (current.message == OPEN_PHONE) "The phone has to be nearby." else "Use the phone for this one.") }
            item { ActionChip("Back", true) { screen = Screen.Home } }
        }
    }
}

@Composable
private fun WearPage(content: ScalingLazyListScope.() -> Unit) {
    MaterialTheme {
        val state = rememberScalingLazyListState()
        Scaffold(
            timeText = { TimeText() },
            positionIndicator = { PositionIndicator(scalingLazyListState = state) },
        ) {
            ScalingLazyColumn(
                modifier = Modifier.fillMaxSize(),
                state = state,
                contentPadding = PaddingValues(horizontal = 8.dp, vertical = 32.dp),
                autoCentering = null,
                content = content,
            )
        }
    }
}

@Composable
private fun Title(text: String) {
    Text(
        text = text,
        textAlign = TextAlign.Center,
        maxLines = 3,
        overflow = TextOverflow.Ellipsis,
        modifier = Modifier.fillMaxWidth(),
    )
}

@Composable
private fun Body(text: String) {
    Text(
        text = text,
        textAlign = TextAlign.Center,
        maxLines = 5,
        overflow = TextOverflow.Ellipsis,
        modifier = Modifier.fillMaxWidth().padding(vertical = 2.dp),
    )
}

@Composable
private fun ActionChip(label: String, enabled: Boolean, onClick: () -> Unit) {
    Chip(
        modifier = Modifier.fillMaxWidth(),
        enabled = enabled,
        onClick = onClick,
        label = { Text(label, maxLines = 2, overflow = TextOverflow.Ellipsis) },
    )
}
