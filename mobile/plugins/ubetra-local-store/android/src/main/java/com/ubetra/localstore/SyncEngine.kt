package com.ubetra.localstore

import android.content.Context
import android.util.Log
import org.json.JSONObject
import java.io.OutputStream
import java.net.HttpURLConnection
import java.net.URL

/**
 * Push pending chastity and orgasm rows, then pull. A local row stays until the
 * server accepts it. If the server copy is older, the pending row is kept.
 */
class SyncEngine(context: Context) {
    private val appContext = context.applicationContext
    private val store = LocalStore.get(appContext)
    fun configured(): Boolean = store.getServerConfig().optBoolean("serverConfigured")

    fun probe(): Boolean {
        val base = store.apiBase()
        if (base.isBlank()) {
            store.markReachable(false)
            return false
        }
        val result = request("$base/api/health", "GET", "", null)
        val ok = result.code in 200..299
        store.markReachable(ok)
        return ok
    }

    fun pushPull(): JSONObject {
        val pushed = pushPending()
        val pulled = pull()
        WearBridge.publishSummary(appContext)
        return JSONObject().put("pushed", pushed).put("pulled", pulled).put("pending", store.pendingEvents().size)
    }

    private fun pushPending(): Int {
        val base = store.apiBase()
        val token = store.token()
        val dynamicId = store.dynamicId()
        if (base.isBlank() || token.isBlank() || dynamicId.isBlank() || dynamicId == "local") return 0
        var pushed = 0
        store.pendingEvents().forEach { event ->
            val action = event.optString("action")
            val body = event.optJSONObject("body") ?: JSONObject()
            val localLock = event.optString("local_lockup_id")
            val serverLock = store.serverIdForLockup(localLock)
            val path = when (action) {
                "log_full", "log_ruined", "log_denied", "log_play" -> "/api/dynamics/$dynamicId/tracking"
                "start" -> "/api/dynamics/$dynamicId/chastity/start"
                "end" -> {
                    if (serverLock.isBlank()) return@forEach
                    "/api/dynamics/$dynamicId/chastity/$serverLock/end"
                }
                "sleep_break", "hygiene_break" -> {
                    if (serverLock.isBlank()) return@forEach
                    "/api/dynamics/$dynamicId/chastity/$serverLock/break"
                }
                "relock" -> {
                    val breakId = store.serverBreakId(localLock)
                    if (serverLock.isBlank() || breakId.isBlank()) return@forEach
                    "/api/dynamics/$dynamicId/chastity/$serverLock/break/$breakId/finish"
                }
                else -> return@forEach
            }
            val method = if (action == "end" || action == "relock") "PATCH" else "POST"
            val result = request(base + path, method, token, body.toString())
            if (result.code == 401 || result.code == 403) return pushed
            if (result.code !in 200..299) return@forEach
            val parsed = try {
                JSONObject(result.body)
            } catch (_: Exception) {
                JSONObject()
            }
            val serverId = parsed.optString("id")
            val breakId = activeBreakId(parsed)
            store.attachServerResult(event.optString("client_event_id"), serverId.ifBlank { serverLock }, breakId)
            pushed += 1
        }
        return pushed
    }

    private fun pull(): Boolean {
        val base = store.apiBase()
        val token = store.token()
        val dynamicId = store.dynamicId()
        if (base.isBlank() || token.isBlank() || dynamicId.isBlank() || dynamicId == "local") return false
        val overview = request("$base/api/dynamics/$dynamicId/chastity/overview", "GET", token, null)
        val lockups = request("$base/api/dynamics/$dynamicId/chastity", "GET", token, null)
        val tracking = request("$base/api/dynamics/$dynamicId/tracking", "GET", token, null)
        val summary = request("$base/api/dynamics/$dynamicId/watch/summary", "GET", token, null)
        if (overview.code == 401 || tracking.code == 401) return false
        store.savePull(
            overview = if (overview.code in 200..299) overview.body else null,
            lockups = if (lockups.code in 200..299) lockups.body else null,
            tracking = if (tracking.code in 200..299) tracking.body else null,
            summary = if (summary.code in 200..299) summary.body else null,
        )
        return overview.code in 200..299 || tracking.code in 200..299
    }

    private fun activeBreakId(lockup: JSONObject): String? {
        val breaks = lockup.optJSONArray("breaks") ?: return null
        for (i in 0 until breaks.length()) {
            val row = breaks.optJSONObject(i) ?: continue
            if (row.isNull("ended_at") || row.optString("ended_at").isBlank()) {
                return row.optString("id").ifBlank { null }
            }
        }
        return null
    }

    private fun request(url: String, method: String, token: String, body: String?): HttpResult {
        val connection = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = 15000
            readTimeout = 20000
            instanceFollowRedirects = false
            setRequestProperty("Accept", "application/json")
            setRequestProperty("User-Agent", "UBETRA-Phone")
            if (token.isNotBlank()) setRequestProperty("Authorization", "Bearer $token")
            if (body != null && method != "GET" && method != "HEAD") {
                doOutput = true
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
            }
        }
        try {
            if (body != null && method != "GET" && method != "HEAD") {
                connection.outputStream.use { stream: OutputStream -> stream.write(body.toByteArray(Charsets.UTF_8)) }
            }
            val code = connection.responseCode
            val stream = if (code in 200..299) connection.inputStream else connection.errorStream
            val text = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
            Log.i(TAG, "$method ${url.substringAfter("/api")} -> $code")
            return HttpResult(code, text)
        } catch (err: Exception) {
            Log.i(TAG, "$method failed ${err.javaClass.simpleName}")
            return HttpResult(0, "")
        } finally {
            connection.disconnect()
        }
    }

    private data class HttpResult(val code: Int, val body: String)

    companion object {
        private const val TAG = "UbetraSync"
    }
}
