package com.ubetra.localstore

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import org.json.JSONArray
import org.json.JSONObject
import java.time.Duration
import java.time.Instant
import java.util.UUID

/**
 * Phone SQLite log. Pending rows are never deleted. Newer updated_at wins when
 * a pulled server copy is compared with an unpushed local row.
 */
class LocalStore private constructor(context: Context) {
    private val appContext = context.applicationContext
    private val helper = Helper(appContext)
    private val db: SQLiteDatabase = helper.writableDatabase
    private val secrets = SecretStore(appContext)

    fun secrets(): SecretStore = secrets

    @Synchronized
    fun getServerConfig(): JSONObject {
        val url = meta("server_url")
        val choice = meta("server_choice")
        val phoneOnly = choice == "phone" || url.isBlank() && choice == "phone"
        val configured = url.isNotBlank() && choice == "url"
        return JSONObject()
            .put("serverUrl", url)
            .put("phoneOnly", choice == "phone")
            .put("choiceMade", choice == "phone" || choice == "url")
            .put("serverConfigured", configured)
            .put("serverReachable", meta("server_reachable") == "1")
            .put("lastSyncAt", meta("last_sync_at"))
            .put("pendingCount", pendingCount())
            .put("localLoggerReady", true)
    }

    @Synchronized
    fun setServerUrl(raw: String): JSONObject {
        val url = normalizeUrl(raw)
        putMeta("server_url", url)
        putMeta("server_choice", "url")
        putMeta("server_reachable", "0")
        return getServerConfig()
    }

    @Synchronized
    fun setPhoneOnly(): JSONObject {
        putMeta("server_url", "")
        putMeta("server_choice", "phone")
        putMeta("server_reachable", "0")
        return getServerConfig()
    }

    @Synchronized
    fun setSession(token: String, dynamicId: String, membershipId: String, apiBase: String, dynamicJson: String, userJson: String) {
        if (token.isNotBlank() && token != "local") secrets.setToken(token)
        if (dynamicId.isNotBlank() && dynamicId != "local") putMeta("dynamic_id", dynamicId)
        if (membershipId.isNotBlank()) putMeta("membership_id", membershipId)
        if (apiBase.isNotBlank()) putMeta("api_base", apiBase.trimEnd('/'))
        if (dynamicJson.isNotBlank() && dynamicJson != "null") putMeta("dynamic_json", dynamicJson)
        if (userJson.isNotBlank() && userJson != "null") putMeta("user_json", userJson)
    }

    fun token(): String = secrets.token()

    fun apiBase(): String {
        val saved = meta("api_base")
        if (saved.isNotBlank()) return saved.trimEnd('/')
        return meta("server_url").trimEnd('/')
    }

    fun dynamicId(): String = meta("dynamic_id").ifBlank { "local" }

    fun membershipId(): String = meta("membership_id").ifBlank { "local-self" }

    @Synchronized
    fun markReachable(ok: Boolean) {
        putMeta("server_reachable", if (ok) "1" else "0")
    }

    @Synchronized
    fun logOrgasm(body: JSONObject): JSONObject {
        val now = Instant.now().toString()
        val id = body.optString("client_event_id").ifBlank { UUID.randomUUID().toString() }
        val action = body.optString("action").ifBlank { actionForOrgasm(body) }
        val apiBody = JSONObject(body.toString())
        apiBody.put("client_event_id", id)
        apiBody.put("updated_at", body.optString("updated_at").ifBlank { now })
        if (!apiBody.has("for_membership_id") || apiBody.optString("for_membership_id").isBlank()) {
            apiBody.put("for_membership_id", membershipId())
        }
        if (!apiBody.has("occurred_at")) apiBody.put("occurred_at", now)
        val event = JSONObject()
            .put("client_event_id", id)
            .put("kind", "orgasm")
            .put("action", action)
            .put("updated_at", apiBody.optString("updated_at"))
            .put("body", apiBody)
        insertPending(event)
        return entryFromEvent(event)
    }

    @Synchronized
    fun chastityAction(body: JSONObject): JSONObject {
        val action = body.optString("action").ifBlank { "start" }
        val now = Instant.now().toString()
        val id = body.optString("client_event_id").ifBlank { UUID.randomUUID().toString() }
        val view = replay()
        val active = view.optJSONObject("active")
        val apiBody = JSONObject()
        apiBody.put("client_event_id", id)
        apiBody.put("updated_at", body.optString("updated_at").ifBlank { now })
        val forId = body.optString("for_membership_id").ifBlank { membershipId() }
        when (action) {
            "start", "lock" -> {
                if (active != null) return status()
                apiBody.put("for_membership_id", forId)
                apiBody.put("device_notes", body.optString("device_notes"))
                apiBody.put("started_at", body.optString("started_at").ifBlank { now })
            }
            "end", "unlock" -> {
                if (active == null) return status()
                apiBody.put("release_notes", body.optString("release_notes"))
                apiBody.put("ended_at", body.optString("ended_at").ifBlank { now })
                apiBody.put("ended_kind", body.optString("ended_kind").ifBlank { "unlocked" })
            }
            "sleep_break", "hygiene_break" -> {
                if (active == null || active.optBoolean("on_break")) return status()
                val type = if (action == "sleep_break") "authorized_sleep" else "authorized_hygiene"
                apiBody.put("break_type", type)
                apiBody.put("break_reason", if (action == "sleep_break") "Sleep" else "Hygiene")
                apiBody.put("started_at", now)
            }
            "relock" -> {
                if (active == null || !active.optBoolean("on_break")) return status()
                apiBody.put("ended_at", now)
            }
            else -> return status()
        }
        val event = JSONObject()
            .put("client_event_id", id)
            .put("kind", "chastity")
            .put("action", if (action == "lock") "start" else if (action == "unlock") "end" else action)
            .put("updated_at", apiBody.optString("updated_at"))
            .put("local_lockup_id", active?.optString("local_lockup_id").orEmpty().ifBlank {
                if (action == "start" || action == "lock") "local-" + UUID.randomUUID().toString() else ""
            })
            .put("local_break_id", if (action.endsWith("break")) "break-" + UUID.randomUUID().toString() else active?.optString("local_break_id").orEmpty())
            .put("body", apiBody)
        if (event.optString("local_lockup_id").isBlank() && active != null) {
            event.put("local_lockup_id", active.optString("local_lockup_id"))
        }
        insertPending(event)
        return status()
    }

    @Synchronized
    fun status(): JSONObject {
        val config = getServerConfig()
        val chastity = chastityDocument()
        val entries = recentEntries()
        val summary = watchSummary(chastity, entries)
        val dynamic = storedDynamic()
        return JSONObject()
            .put("localLoggerReady", true)
            .put("serverConfigured", config.optBoolean("serverConfigured"))
            .put("serverReachable", config.optBoolean("serverReachable"))
            .put("phoneOnly", config.optBoolean("phoneOnly"))
            .put("pendingCount", config.optInt("pendingCount"))
            .put("lastSyncAt", config.optString("lastSyncAt"))
            .put("overview", chastity.optJSONObject("overview"))
            .put("lockups", chastity.optJSONArray("lockups"))
            .put("entries", entries)
            .put("stats", statsFrom(entries))
            .put("summary", summary)
            .put("sleep", snapshotArray("sleep_json"))
            .put("cycle", snapshotObject("cycle_json"))
            .put("dynamic", dynamic)
            .put("user", storedUser())
    }

    @Synchronized
    fun listRecent(): JSONObject = JSONObject().put("entries", recentEntries())

    @Synchronized
    fun pendingEvents(): List<JSONObject> {
        val out = ArrayList<JSONObject>()
        db.query("events", null, "sync_state=?", arrayOf("pending"), null, null, "updated_at ASC").use { cursor ->
            while (cursor.moveToNext()) out.add(rowToEvent(cursor))
        }
        return out
    }

    @Synchronized
    fun markSynced(clientEventId: String, serverId: String?) {
        val values = ContentValues()
        values.put("sync_state", "synced")
        if (!serverId.isNullOrBlank()) values.put("server_id", serverId)
        db.update("events", values, "client_event_id=?", arrayOf(clientEventId))
    }

    @Synchronized
    fun attachServerResult(clientEventId: String, serverLockId: String, serverBreakId: String?) {
        val event = findEvent(clientEventId) ?: return
        if (serverLockId.isNotBlank()) event.put("server_lockup_id", serverLockId)
        if (!serverBreakId.isNullOrBlank()) event.put("server_break_id", serverBreakId)
        val values = ContentValues()
        values.put("sync_state", "synced")
        if (serverLockId.isNotBlank()) values.put("server_id", serverLockId)
        values.put("payload_json", event.toString())
        db.update("events", values, "client_event_id=?", arrayOf(clientEventId))
    }

    @Synchronized
    fun serverBreakId(localLockupId: String): String {
        if (localLockupId.isBlank()) return ""
        db.query("events", arrayOf("payload_json"), "kind=?", arrayOf("chastity"), null, null, "updated_at DESC").use { cursor ->
            while (cursor.moveToNext()) {
                val payload = JSONObject(cursor.getString(0))
                if (payload.optString("local_lockup_id") != localLockupId) continue
                val breakId = payload.optString("server_break_id")
                if (breakId.isNotBlank()) return breakId
            }
        }
        return ""
    }

    @Synchronized
    fun noteServerWins(clientEventId: String, serverUpdatedAt: String) {
        val local = findEvent(clientEventId) ?: return
        if (local.optString("sync_state") != "pending") return
        if (isNewer(local.optString("updated_at"), serverUpdatedAt)) return
        markSynced(clientEventId, local.optString("server_id"))
    }

    @Synchronized
    fun serverIdForLockup(localLockupId: String): String {
        if (localLockupId.isBlank()) return ""
        db.query("events", arrayOf("server_id", "payload_json"), "kind=?", arrayOf("chastity"), null, null, "updated_at ASC").use { cursor ->
            while (cursor.moveToNext()) {
                val serverId = cursor.getString(0).orEmpty()
                val payload = JSONObject(cursor.getString(1))
                if (payload.optString("local_lockup_id") == localLockupId && serverId.isNotBlank()) {
                    return serverId
                }
            }
        }
        return ""
    }

    @Synchronized
    fun savePull(overview: String?, lockups: String?, tracking: String?, summary: String?) {
        val values = ContentValues()
        values.put("id", 1)
        if (overview != null) values.put("overview_json", overview)
        if (lockups != null) values.put("lockups_json", lockups)
        if (tracking != null) values.put("recent_json", tracking)
        if (summary != null) {
            values.put("summary_json", summary)
            try {
                val json = JSONObject(summary)
                val sleep = json.optJSONObject("sleep")
                val cycle = json.optJSONObject("cycle")
                if (sleep != null) values.put("sleep_json", sleep.toString())
                if (cycle != null) values.put("cycle_json", cycle.toString())
            } catch (_: Exception) {
            }
        }
        values.put("updated_at", Instant.now().toString())
        db.insertWithOnConflict("snapshot", null, values, SQLiteDatabase.CONFLICT_REPLACE)
        putMeta("last_sync_at", Instant.now().toString())
        absorbServerRows(tracking, lockups)
    }

    @Synchronized
    fun watchSummaryJson(): JSONObject {
        val chastity = chastityDocument()
        return watchSummary(chastity, recentEntries())
    }

    fun hasPending(): Boolean = pendingCount() > 0

    @Synchronized
    fun setPairCode(code: String) {
        putMeta("wear_pair_code", code)
        putMeta("wear_pair_exp", (System.currentTimeMillis() + 5 * 60 * 1000).toString())
    }

    @Synchronized
    fun pairCodeMatches(code: String): Boolean {
        val saved = meta("wear_pair_code")
        val exp = meta("wear_pair_exp").toLongOrNull() ?: 0L
        if (saved.isBlank() || System.currentTimeMillis() > exp) return false
        return saved == code
    }

    @Synchronized
    fun clearPairCode() {
        putMeta("wear_pair_code", "")
        putMeta("wear_pair_exp", "0")
    }

    private fun absorbServerRows(tracking: String?, lockups: String?) {
        if (!tracking.isNullOrBlank()) {
            val rows = JSONArray(tracking)
            for (i in 0 until rows.length()) {
                val row = rows.optJSONObject(i) ?: continue
                val cid = row.optString("client_event_id")
                if (cid.isNotBlank()) noteServerWins(cid, row.optString("updated_at", row.optString("occurred_at")))
            }
        }
        if (!lockups.isNullOrBlank()) {
            val rows = JSONArray(lockups)
            for (i in 0 until rows.length()) {
                val row = rows.optJSONObject(i) ?: continue
                val cid = row.optString("client_event_id")
                if (cid.isNotBlank()) noteServerWins(cid, row.optString("updated_at", row.optString("started_at")))
            }
        }
    }

    private fun chastityDocument(): JSONObject {
        val pending = countKindPending("chastity") > 0
        val localAt = newestKind("chastity")
        val snapAt = snapshotTime()
        val replayed = replay()
        val hasLocal = replayed.optBoolean("has_events")
        if (pending || (hasLocal && (snapAt.isBlank() || isNewer(localAt, snapAt) || localAt == snapAt))) {
            return replayed
        }
        val overview = snapshotObject("overview_json")
        val lockups = snapshotArray("lockups_json")
        if (overview != null) {
            return JSONObject().put("overview", overview).put("lockups", lockups ?: JSONArray()).put("has_events", hasLocal)
        }
        return replayed
    }

    private fun replay(): JSONObject {
        val events = allEvents().filter { it.optString("kind") == "chastity" }
        var localId = ""
        var serverId = ""
        var started = ""
        var ended: String? = null
        var onBreak = false
        var breakLabel = ""
        var breakId = ""
        var breakStarted = ""
        var active = false
        events.forEach { event ->
            val action = event.optString("action")
            val at = event.optString("updated_at")
            when (action) {
                "start" -> {
                    localId = event.optString("local_lockup_id").ifBlank { "local-" + event.optString("client_event_id") }
                    serverId = event.optString("server_id")
                    started = event.optJSONObject("body")?.optString("started_at").orEmpty().ifBlank { at }
                    ended = null
                    onBreak = false
                    breakLabel = ""
                    breakId = ""
                    active = true
                }
                "end" -> {
                    ended = event.optJSONObject("body")?.optString("ended_at").orEmpty().ifBlank { at }
                    onBreak = false
                    active = false
                }
                "sleep_break", "hygiene_break" -> {
                    if (!active) return@forEach
                    onBreak = true
                    breakLabel = if (action == "sleep_break") "Sleep" else "Hygiene"
                    breakId = event.optString("local_break_id")
                    breakStarted = at
                }
                "relock" -> {
                    onBreak = false
                    breakLabel = ""
                    breakId = ""
                }
            }
            if (event.optString("server_id").isNotBlank()) serverId = event.optString("server_id")
        }
        val stateName = when {
            !active -> "unlocked"
            onBreak -> "on_break"
            else -> "locked"
        }
        val duration = if (started.isBlank()) "" else durationLabel(if (onBreak) breakStarted.ifBlank { started } else started, ended)
        val partner = JSONObject()
            .put("membership_id", membershipId())
            .put("name", "You")
            .put("chastity_enabled", true)
            .put("state", stateName)
            .put("current_duration_label", if (stateName == "locked") duration else JSONObject.NULL)
            .put("break_duration_label", if (stateName == "on_break") duration else JSONObject.NULL)
            .put("free_duration_label", if (stateName == "unlocked" && started.isNotBlank()) durationLabel(ended ?: started, null) else JSONObject.NULL)
            .put("timer_overdue", false)
            .put("active_lockup_id", if (active) localId else JSONObject.NULL)
            .put("break_label", breakLabel)
        val summary = when (stateName) {
            "locked" -> if (duration.isBlank()) "Locked" else "Locked · $duration"
            "on_break" -> if (breakLabel.isBlank()) "On a break" else "On a $breakLabel break"
            else -> "Unlocked"
        }
        val overview = JSONObject()
            .put("summary_label", summary)
            .put("any_enabled", true)
            .put("partners", JSONArray().put(partner))
        val lockups = JSONArray()
        if (started.isNotBlank()) {
            lockups.put(
                JSONObject()
                    .put("id", localId.ifBlank { serverId })
                    .put("status", if (active) "active" else "ended")
                    .put("started_at", started)
                    .put("ended_at", ended ?: JSONObject.NULL)
                    .put("for_membership_id", membershipId())
            )
        }
        val activeObj = if (!active) null else JSONObject()
            .put("local_lockup_id", localId)
            .put("server_id", serverId)
            .put("local_break_id", breakId)
            .put("on_break", onBreak)
        val doc = JSONObject()
            .put("overview", overview)
            .put("lockups", lockups)
            .put("has_events", events.isNotEmpty())
        if (activeObj != null) doc.put("active", activeObj)
        return doc
    }

    private fun watchSummary(chastity: JSONObject, entries: JSONArray): JSONObject {
        val overview = chastity.optJSONObject("overview") ?: JSONObject()
        val partner = overview.optJSONArray("partners")?.optJSONObject(0)
        val stateName = partner?.optString("state") ?: "unlocked"
        val subjects = JSONArray()
        if (partner != null) {
            subjects.put(
                JSONObject()
                    .put("name", partner.optString("name", "You"))
                    .put("state", stateName)
                    .put("duration_label", partner.optString("current_duration_label", partner.optString("break_duration_label")))
                    .put("timer_overdue", false)
                    .put("break_label", partner.optString("break_label"))
                    .put("chastity_enabled", true)
                    .put("membership_id", partner.optString("membership_id"))
                    .put("active_lockup_id", partner.opt("active_lockup_id"))
            )
        }
        val actions = JSONArray()
        fun action(id: String, label: String) {
            actions.put(
                JSONObject()
                    .put("id", id)
                    .put("label", label)
                    .put("method", "POST")
                    .put("path", "/local/$id")
                    .put("for_membership_id", membershipId())
                    .put("subject_name", "You")
                    .put("finish_on_phone", false)
            )
        }
        when (stateName) {
            "locked" -> {
                action("sleep_break", "Sleep break")
                action("hygiene_break", "Hygiene break")
                action("unlock", "Unlock")
            }
            "on_break" -> action("relock", "Relock")
            else -> action("lock", "Lock")
        }
        action("log_full", "Full")
        action("log_ruined", "Ruined")
        action("log_denied", "Denied")
        action("log_play", "Play")
        val recentLabel = if (entries.length() == 0) "" else entries.getJSONObject(0).optString("notes").ifBlank {
            val org = entries.getJSONObject(0).optJSONArray("orgasms")?.optJSONObject(0)
            org?.optJSONArray("tags")?.optString(0) ?: "Logged"
        }
        val sleep = snapshotObject("sleep_json")
        val cycle = snapshotObject("cycle_json")
        return JSONObject()
            .put("dynamic_id", dynamicId())
            .put("role", "submissive")
            .put("display_name", "You")
            .put("chastity", JSONObject().put("enabled", true).put("summary_label", overview.optString("summary_label")).put("subjects", subjects))
            .put("sleep", sleep ?: JSONObject().put("enabled", false).put("nights", JSONArray()))
            .put("cycle", cycle ?: JSONObject().put("enabled", false).put("people", JSONArray()))
            .put("orgasm", JSONObject().put("enabled", true).put("recent_orgasm_label", recentLabel).put("partners", JSONArray().put(JSONObject().put("name", "You").put("count_7d", countRecent(entries)))))
            .put("allowed_actions", actions)
    }

    private fun recentEntries(): JSONArray {
        val out = JSONArray()
        val seen = HashSet<String>()
        allEvents().filter { it.optString("kind") == "orgasm" }.asReversed().forEach { event ->
            val entry = entryFromEvent(event)
            seen.add(event.optString("client_event_id"))
            out.put(entry)
        }
        val snap = snapshotArray("recent_json")
        if (snap != null) {
            for (i in 0 until snap.length()) {
                val row = snap.optJSONObject(i) ?: continue
                val cid = row.optString("client_event_id")
                val id = row.optString("id")
                if (cid.isNotBlank() && seen.contains(cid)) continue
                if (id.isNotBlank() && seen.contains(id)) continue
                out.put(row)
            }
        }
        return out
    }

    private fun entryFromEvent(event: JSONObject): JSONObject {
        val body = event.optJSONObject("body") ?: JSONObject()
        val id = event.optString("server_id").ifBlank { event.optString("client_event_id") }
        return JSONObject()
            .put("id", id)
            .put("client_event_id", event.optString("client_event_id"))
            .put("for_membership_id", body.optString("for_membership_id", membershipId()))
            .put("for_display_name", "You")
            .put("event_type", body.optString("event_type", "orgasm"))
            .put("notes", body.optString("notes"))
            .put("tags", body.optJSONArray("tags") ?: JSONArray())
            .put("orgasms", body.optJSONArray("orgasms") ?: JSONArray())
            .put("occurred_at", body.optString("occurred_at", event.optString("updated_at")))
            .put("logged_by_display_name", "You")
            .put("updated_at", event.optString("updated_at"))
            .put("pending", event.optString("sync_state") != "synced")
    }

    private fun statsFrom(entries: JSONArray): JSONObject {
        return JSONObject()
            .put("recent_orgasm_label", if (entries.length() == 0) "Nothing logged yet" else "Logged on this phone")
            .put("partners", JSONArray().put(JSONObject().put("membership_id", membershipId()).put("name", "You").put("orgasm_count", countRecent(entries))))
            .put("cumulative_30d", JSONArray())
    }

    private fun countRecent(entries: JSONArray): Int {
        val cutoff = Instant.now().minus(Duration.ofDays(7))
        var n = 0
        for (i in 0 until entries.length()) {
            val at = entries.optJSONObject(i)?.optString("occurred_at").orEmpty()
            val whenAt = parseInstant(at) ?: continue
            if (!whenAt.isBefore(cutoff)) n += 1
        }
        return n
    }

    private fun storedDynamic(): JSONObject {
        val raw = meta("dynamic_json")
        if (raw.isNotBlank()) {
            try {
                return JSONObject(raw)
            } catch (_: Exception) {
            }
        }
        val id = dynamicId()
        val you = JSONObject()
            .put("id", membershipId())
            .put("display_name", "You")
            .put("is_you", true)
            .put("role", "submissive")
            .put("chastity_enabled", true)
        return JSONObject()
            .put("id", id)
            .put("name", if (id == "local") "This phone" else "UBETRA")
            .put("enabled_features", JSONArray().put("chastity").put("org_tracking"))
            .put("partners", JSONArray().put(you))
    }

    private fun storedUser(): JSONObject {
        val raw = meta("user_json")
        if (raw.isNotBlank()) {
            try {
                return JSONObject(raw)
            } catch (_: Exception) {
            }
        }
        return JSONObject()
            .put("id", "local-user")
            .put("username", "You")
            .put("onboarding_completed", true)
            .put("email", "")
    }

    private fun insertPending(event: JSONObject) {
        val values = ContentValues()
        values.put("client_event_id", event.getString("client_event_id"))
        values.put("kind", event.optString("kind"))
        values.put("action", event.optString("action"))
        values.put("payload_json", event.toString())
        values.put("updated_at", event.optString("updated_at"))
        values.put("sync_state", "pending")
        val inserted = db.insertWithOnConflict("events", null, values, SQLiteDatabase.CONFLICT_IGNORE)
        if (inserted == -1L) {
            // Same client id already stored. Keep the unpushed row.
        }
    }

    private fun allEvents(): List<JSONObject> {
        val out = ArrayList<JSONObject>()
        db.query("events", null, null, null, null, null, "updated_at ASC").use { cursor ->
            while (cursor.moveToNext()) out.add(rowToEvent(cursor))
        }
        return out
    }

    private fun findEvent(id: String): JSONObject? {
        db.query("events", null, "client_event_id=?", arrayOf(id), null, null, null).use { cursor ->
            if (!cursor.moveToFirst()) return null
            return rowToEvent(cursor)
        }
    }

    private fun rowToEvent(cursor: android.database.Cursor): JSONObject {
        val payload = JSONObject(cursor.getString(cursor.getColumnIndexOrThrow("payload_json")))
        payload.put("sync_state", cursor.getString(cursor.getColumnIndexOrThrow("sync_state")))
        payload.put("server_id", cursor.getString(cursor.getColumnIndexOrThrow("server_id")).orEmpty())
        return payload
    }

    private fun pendingCount(): Int {
        db.rawQuery("SELECT COUNT(*) FROM events WHERE sync_state='pending'", null).use { cursor ->
            if (!cursor.moveToFirst()) return 0
            return cursor.getInt(0)
        }
    }

    private fun countKindPending(kind: String): Int {
        db.rawQuery("SELECT COUNT(*) FROM events WHERE sync_state='pending' AND kind=?", arrayOf(kind)).use { cursor ->
            if (!cursor.moveToFirst()) return 0
            return cursor.getInt(0)
        }
    }

    private fun newestKind(kind: String): String {
        db.rawQuery("SELECT updated_at FROM events WHERE kind=? ORDER BY updated_at DESC LIMIT 1", arrayOf(kind)).use { cursor ->
            if (!cursor.moveToFirst()) return ""
            return cursor.getString(0).orEmpty()
        }
    }

    private fun snapshotTime(): String {
        db.rawQuery("SELECT updated_at FROM snapshot WHERE id=1", null).use { cursor ->
            if (!cursor.moveToFirst()) return ""
            return cursor.getString(0).orEmpty()
        }
    }

    private fun snapshotObject(column: String): JSONObject? {
        val text = snapshotColumn(column)
        if (text.isBlank()) return null
        return try {
            JSONObject(text)
        } catch (_: Exception) {
            null
        }
    }

    private fun snapshotArray(column: String): JSONArray? {
        val text = snapshotColumn(column)
        if (text.isBlank()) return null
        return try {
            JSONArray(text)
        } catch (_: Exception) {
            null
        }
    }

    private fun snapshotColumn(column: String): String {
        db.rawQuery("SELECT $column FROM snapshot WHERE id=1", null).use { cursor ->
            if (!cursor.moveToFirst()) return ""
            return cursor.getString(0).orEmpty()
        }
    }

    private fun meta(key: String): String {
        db.query("meta", arrayOf("v"), "k=?", arrayOf(key), null, null, null).use { cursor ->
            if (!cursor.moveToFirst()) return ""
            return cursor.getString(0).orEmpty()
        }
    }

    private fun putMeta(key: String, value: String) {
        val values = ContentValues()
        values.put("k", key)
        values.put("v", value)
        db.insertWithOnConflict("meta", null, values, SQLiteDatabase.CONFLICT_REPLACE)
    }

    private fun actionForOrgasm(body: JSONObject): String {
        val orgasms = body.optJSONArray("orgasms")
        val tag = orgasms?.optJSONObject(0)?.optJSONArray("tags")?.optString(0).orEmpty()
        return when {
            tag.contains("ruin", true) -> "log_ruined"
            tag.contains("denied", true) -> "log_denied"
            body.optString("event_type") == "no_orgasm" -> "log_play"
            else -> "log_full"
        }
    }

    private fun durationLabel(startIso: String, endIso: String?): String {
        val start = parseInstant(startIso) ?: return ""
        val end = if (endIso.isNullOrBlank()) Instant.now() else parseInstant(endIso) ?: Instant.now()
        val mins = Duration.between(start, end).toMinutes().coerceAtLeast(0)
        val hours = mins / 60
        val rem = mins % 60
        return if (hours > 0) "${hours}h ${rem}m" else "${rem}m"
    }

    private fun isNewer(left: String, right: String): Boolean {
        val a = parseInstant(left) ?: return false
        val b = parseInstant(right) ?: return true
        return a.isAfter(b)
    }

    private fun parseInstant(value: String): Instant? {
        if (value.isBlank()) return null
        return try {
            Instant.parse(value)
        } catch (_: Exception) {
            try {
                Instant.parse(if (value.endsWith("Z")) value else value + "Z")
            } catch (_: Exception) {
                null
            }
        }
    }

    private fun normalizeUrl(raw: String): String {
        val trimmed = raw.trim().trimEnd('/')
        val scheme = trimmed.substringBefore("://", "").lowercase()
        if (scheme != "https" && scheme != "http") {
            throw IllegalArgumentException("Server must be an http(s) URL")
        }
        val host = trimmed.substringAfter("://").substringBefore("/").substringBefore("?")
        if (host.isBlank()) throw IllegalArgumentException("Server must be an http(s) URL")
        return trimmed
    }

    private class Helper(context: Context) : SQLiteOpenHelper(context, "ubetra_local.db", null, 1) {
        override fun onCreate(db: SQLiteDatabase) {
            db.execSQL("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT NOT NULL)")
            db.execSQL(
                "CREATE TABLE events (" +
                    "client_event_id TEXT PRIMARY KEY," +
                    "kind TEXT NOT NULL," +
                    "action TEXT NOT NULL," +
                    "payload_json TEXT NOT NULL," +
                    "updated_at TEXT NOT NULL," +
                    "server_id TEXT," +
                    "sync_state TEXT NOT NULL)"
            )
            db.execSQL(
                "CREATE TABLE snapshot (" +
                    "id INTEGER PRIMARY KEY CHECK (id = 1)," +
                    "overview_json TEXT," +
                    "lockups_json TEXT," +
                    "recent_json TEXT," +
                    "sleep_json TEXT," +
                    "cycle_json TEXT," +
                    "summary_json TEXT," +
                    "updated_at TEXT)"
            )
        }

        override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit
    }

    companion object {
        @Volatile
        private var instance: LocalStore? = null

        fun get(context: Context): LocalStore {
            return instance ?: synchronized(this) {
                instance ?: LocalStore(context.applicationContext).also { instance = it }
            }
        }
    }
}
