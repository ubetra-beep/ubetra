package com.ubetra.wear

import org.json.JSONArray
import org.json.JSONObject

data class DynamicRef(
    val id: String,
    val name: String,
)

data class WatchAction(
    val id: String,
    val label: String,
    val method: String,
    val path: String,
    val forMembershipId: String,
    val subjectName: String,
    val finishOnPhone: Boolean,
    val body: JSONObject?,
) {
    val key: String get() = "$id:$forMembershipId"
}

data class ChastitySubject(
    val name: String,
    val state: String,
    val durationLabel: String?,
    val timerOverdue: Boolean,
    val breakLabel: String?,
)

data class SleepNight(
    val name: String,
    val isYou: Boolean,
    val durationMin: Int?,
    val durationLabel: String?,
)

data class CyclePerson(
    val name: String,
    val isYou: Boolean,
    val cycleDay: Int?,
    val onPeriod: Boolean,
)

data class OrgasmPartner(
    val name: String,
    val count7d: Int,
)

data class WatchSummary(
    val dynamicId: String,
    val role: String,
    val displayName: String,
    val chastityEnabled: Boolean,
    val chastitySummary: String,
    val subjects: List<ChastitySubject>,
    val sleepEnabled: Boolean,
    val nights: List<SleepNight>,
    val cycleEnabled: Boolean,
    val people: List<CyclePerson>,
    val orgasmEnabled: Boolean,
    val orgasmLabel: String,
    val partners: List<OrgasmPartner>,
    val actions: List<WatchAction>,
) {
    fun lockActions(): List<WatchAction> = actions.filter { it.id in LOCK_ACTION_IDS }

    fun logActions(): List<WatchAction> = actions.filter { it.id in LOG_ACTION_IDS }

    fun otherActions(): List<WatchAction> =
        actions.filter { it.id !in LOCK_ACTION_IDS && it.id !in LOG_ACTION_IDS }
}

data class ActionOutcome(
    val text: String,
    val refreshSummary: Boolean,
)

class WatchApiException(val status: Int, message: String) : Exception(message)

class WatchSignedOutException : Exception("Watch access revoked")

fun parseSummary(json: JSONObject): WatchSummary {
    val chastity = json.optJSONObject("chastity") ?: JSONObject()
    val sleep = json.optJSONObject("sleep") ?: JSONObject()
    val cycle = json.optJSONObject("cycle") ?: JSONObject()
    val orgasm = json.optJSONObject("orgasm") ?: JSONObject()
    return WatchSummary(
        dynamicId = json.optString("dynamic_id"),
        role = json.optString("role"),
        displayName = json.optString("display_name"),
        chastityEnabled = chastity.optBoolean("enabled"),
        chastitySummary = chastity.optString("summary_label"),
        subjects = chastity.optJSONArray("subjects").objects().map { row ->
            ChastitySubject(
                name = row.optString("name"),
                state = row.optString("state"),
                durationLabel = row.nullableString("duration_label"),
                timerOverdue = row.optBoolean("timer_overdue"),
                breakLabel = row.nullableString("break_label"),
            )
        },
        sleepEnabled = sleep.optBoolean("enabled"),
        nights = sleep.optJSONArray("nights").objects().map { row ->
            SleepNight(
                name = row.optString("name"),
                isYou = row.optBoolean("is_you"),
                durationMin = row.nullableInt("duration_min"),
                durationLabel = row.nullableString("duration_label"),
            )
        },
        cycleEnabled = cycle.optBoolean("enabled"),
        people = cycle.optJSONArray("people").objects().map { row ->
            CyclePerson(
                name = row.optString("name"),
                isYou = row.optBoolean("is_you"),
                cycleDay = row.nullableInt("cycle_day"),
                onPeriod = row.optBoolean("on_period"),
            )
        },
        orgasmEnabled = orgasm.optBoolean("enabled"),
        orgasmLabel = orgasm.optString("recent_orgasm_label"),
        partners = orgasm.optJSONArray("partners").objects().map { row ->
            OrgasmPartner(
                name = row.optString("name"),
                count7d = row.optInt("count_7d"),
            )
        },
        actions = json.optJSONArray("allowed_actions").objects().map { row ->
            val body = row.opt("body")
            WatchAction(
                id = row.optString("id"),
                label = row.optString("label").ifBlank { row.optString("id") },
                method = row.optString("method").ifBlank { "POST" },
                path = row.optString("path"),
                forMembershipId = row.nullableString("for_membership_id").orEmpty(),
                subjectName = row.optString("subject_name"),
                finishOnPhone = row.optBoolean("finish_on_phone"),
                body = body as? JSONObject,
            )
        },
    )
}

fun parseDynamics(body: String): List<DynamicRef> {
    val array = JSONArray(body)
    return (0 until array.length()).map { index ->
        val row = array.getJSONObject(index)
        DynamicRef(
            id = row.optString("id"),
            name = row.optString("name").ifBlank { "Dynamic" },
        )
    }.filter { it.id.isNotBlank() }
}

fun errorDetail(body: String, fallback: String): String {
    return try {
        when (val detail = JSONObject(body).opt("detail")) {
            is String -> detail.ifBlank { fallback }
            is JSONArray -> detail.optJSONObject(0)?.optString("msg").orEmpty().ifBlank { fallback }
            else -> fallback
        }
    } catch (_: Exception) {
        fallback
    }
}

private fun JSONObject.nullableString(key: String): String? {
    if (!has(key) || isNull(key)) return null
    return optString(key).ifBlank { null }
}

private fun JSONObject.nullableInt(key: String): Int? {
    if (!has(key) || isNull(key)) return null
    return optInt(key)
}

private fun JSONArray?.objects(): List<JSONObject> {
    if (this == null) return emptyList()
    return (0 until length()).mapNotNull { index ->
        optJSONObject(index)
    }
}

fun WatchSummary.lockGlance(): GlanceText {
    if (!chastityEnabled) {
        return GlanceText(title = "Lock", shortText = "Off", longText = "Chastity is off")
    }
    val subject = subjects.firstOrNull { it.state == "locked" }
        ?: subjects.firstOrNull { it.state == "on_break" }
        ?: subjects.firstOrNull()
    if (subject == null) {
        val label = chastitySummary.ifBlank { "No lock" }
        return GlanceText(title = "Lock", shortText = "—", longText = label)
    }
    val title = when {
        subject.timerOverdue && subject.state == "locked" -> "Overdue"
        subject.state == "locked" -> "Locked"
        subject.state == "on_break" -> "Break"
        subject.state == "unlocked" -> "Free"
        else -> "Off"
    }
    val duration = subject.durationLabel ?: "—"
    val longText = chastitySummary.ifBlank { "$title $duration" }
    return GlanceText(title = title, shortText = duration, longText = longText)
}

fun WatchSummary.sleepGlance(): GlanceText {
    if (!sleepEnabled) return GlanceText("Sleep", "Off", "Sleep is off")
    val night = nights.firstOrNull { it.isYou && it.hasDuration() }
        ?: nights.firstOrNull { it.hasDuration() }
    if (night == null) return GlanceText("Sleep", "—", "No sleep logged")
    val hours = night.durationLabel ?: "—"
    return GlanceText("Sleep", hours, "Last night $hours")
}

fun WatchSummary.cycleGlance(): GlanceText {
    if (!cycleEnabled) return GlanceText("Cycle", "Off", "Cycle is off")
    val person = people.firstOrNull { it.isYou && it.hasCycle() }
        ?: people.firstOrNull { it.hasCycle() }
    if (person == null) return GlanceText("Cycle", "—", "No cycle day")
    val day = person.cycleDay?.let { "Day $it" }
    val short = when {
        person.onPeriod && day != null -> day
        person.onPeriod -> "Period"
        day != null -> day
        else -> "—"
    }
    val title = if (person.onPeriod) "Period" else "Cycle"
    val long = when {
        person.onPeriod && day != null -> "${person.name} on period, $day"
        person.onPeriod -> "${person.name} on period"
        day != null -> "${person.name} $day"
        else -> "No cycle day"
    }
    return GlanceText(title, short, long)
}

fun WatchSummary.orgasmGlance(): GlanceText {
    if (!orgasmEnabled) return GlanceText("7 days", "Off", "Orgasm log is off")
    val label = orgasmLabel.ifBlank { "—" }
    val short = when {
        label.length <= 22 -> label
        partners.isEmpty() -> label.take(22)
        partners.size == 1 -> partners.first().count7d.toString()
        else -> partners.joinToString(" · ") { it.count7d.toString() }
    }
    return GlanceText("7 days", short, label)
}

private fun SleepNight.hasDuration(): Boolean = durationMin != null || !durationLabel.isNullOrBlank()

private fun CyclePerson.hasCycle(): Boolean = cycleDay != null || onPeriod

data class GlanceText(
    val title: String,
    val shortText: String,
    val longText: String,
)
