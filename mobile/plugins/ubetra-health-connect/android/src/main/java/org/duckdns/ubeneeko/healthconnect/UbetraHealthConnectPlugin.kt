package org.duckdns.ubeneeko.healthconnect

import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.result.ActivityResultLauncher
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.MenstruationFlowRecord
import androidx.health.connect.client.records.Record
import androidx.health.connect.client.records.SleepSessionRecord
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import com.getcapacitor.JSArray
import com.getcapacitor.JSObject
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.CapacitorPlugin
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.Instant
import java.time.ZoneOffset
import java.time.temporal.ChronoUnit
import kotlin.reflect.KClass

@CapacitorPlugin(name = "UbetraHealthConnect")
class UbetraHealthConnectPlugin : Plugin() {
    private var permissionCall: PluginCall? = null
    private var requestedPermissions: Set<String> = emptySet()
    private var permissionLauncher: ActivityResultLauncher<Set<String>>? = null

    override fun load() {
        super.load()
        val componentActivity = activity as? ComponentActivity
        if (componentActivity == null) {
            Log.e(TAG, "Activity is not a ComponentActivity")
            return
        }
        permissionLauncher = componentActivity.registerForActivityResult(
            androidx.health.connect.client.PermissionController.createRequestPermissionResultContract()
        ) { granted ->
            val call = permissionCall ?: return@registerForActivityResult
            permissionCall = null
            val requested = requestedPermissions
            val sleepPerm = HealthPermission.getReadPermission(SleepSessionRecord::class)
            val cyclePerm = HealthPermission.getReadPermission(MenstruationFlowRecord::class)
            val historyPerm = "android.permission.health.READ_HEALTH_DATA_HISTORY"
            val sleepOk = sleepPerm in granted
            val cycleOk = cyclePerm in granted
            val ret = JSObject()
            ret.put("sleep", sleepOk)
            ret.put("cycle", cycleOk)
            ret.put("history", historyPerm in granted)
            ret.put(
                "granted",
                (sleepPerm in requested && sleepOk) || (cyclePerm in requested && cycleOk)
            )
            ret.put("grantedCount", granted.size)
            call.resolve(ret)
            requestedPermissions = emptySet()
        }
    }

    @PluginMethod
    fun checkAvailability(call: PluginCall) {
        try {
            val status = HealthConnectClient.getSdkStatus(context)
            val availability = when (status) {
                HealthConnectClient.SDK_AVAILABLE -> "Available"
                HealthConnectClient.SDK_UNAVAILABLE_PROVIDER_UPDATE_REQUIRED -> "NotInstalled"
                else -> "NotSupported"
            }
            val ret = JSObject()
            ret.put("availability", availability)
            call.resolve(ret)
        } catch (err: Exception) {
            call.reject(err.message)
        }
    }

    @PluginMethod
    fun requestAccess(call: PluginCall) {
        val launcher = permissionLauncher
        if (launcher == null) {
            call.reject("Health Connect permission UI is not ready")
            return
        }
        val kind = (call.getString("kind") ?: "both").lowercase()
        requestedPermissions = accessPermissions(kind)
        permissionCall = call
        launcher.launch(requestedPermissions)
    }

    @PluginMethod
    fun exportSleep(call: PluginCall) {
        CoroutineScope(Dispatchers.IO).launch {
            try {
                val client = requireClient()
                requirePermission(client, HealthPermission.getReadPermission(SleepSessionRecord::class))
                val (start, end) = timeWindow(call)
                val records = readAll(client, SleepSessionRecord::class, start, end)
                val sessions = JSArray()
                records.filterIsInstance<SleepSessionRecord>().forEach { record ->
                    val obj = JSObject()
                    obj.put("start_at", record.startTime.toString())
                    obj.put("end_at", record.endTime.toString())
                    obj.put("external_id", record.metadata.id)
                    obj.put("notes", record.notes ?: "")
                    val stages = JSArray()
                    record.stages.forEach { stage ->
                        val row = JSObject()
                        row.put("startTime", stage.startTime.toString())
                        row.put("endTime", stage.endTime.toString())
                        row.put("stage", stage.stage)
                        stages.put(row)
                    }
                    obj.put("stages", stages)
                    sessions.put(obj)
                }
                val history = "android.permission.health.READ_HEALTH_DATA_HISTORY" in
                    client.permissionController.getGrantedPermissions()
                val ret = JSObject()
                ret.put("sessions", sessions)
                ret.put("since", start.toString())
                ret.put("history", history)
                withContext(Dispatchers.Main) { call.resolve(ret) }
            } catch (err: Exception) {
                Log.e(TAG, "exportSleep failed", err)
                withContext(Dispatchers.Main) { call.reject(err.message) }
            }
        }
    }

    @PluginMethod
    fun exportCycle(call: PluginCall) {
        CoroutineScope(Dispatchers.IO).launch {
            try {
                val client = requireClient()
                requirePermission(client, HealthPermission.getReadPermission(MenstruationFlowRecord::class))
                val (start, end) = timeWindow(call)
                val records = readAll(client, MenstruationFlowRecord::class, start, end)
                val out = JSArray()
                records.filterIsInstance<MenstruationFlowRecord>().forEach { record ->
                    val flow = flowLabel(record.flow)
                    if (flow == null) return@forEach
                    val zone = record.zoneOffset ?: ZoneOffset.systemDefault().rules.getOffset(record.time)
                    val obj = JSObject()
                    obj.put("day", record.time.atOffset(zone).toLocalDate().toString())
                    obj.put("flow", flow)
                    obj.put("external_id", record.metadata.id)
                    out.put(obj)
                }
                val ret = JSObject()
                ret.put("days", out)
                ret.put("since", start.toString())
                withContext(Dispatchers.Main) { call.resolve(ret) }
            } catch (err: Exception) {
                Log.e(TAG, "exportCycle failed", err)
                withContext(Dispatchers.Main) { call.reject(err.message) }
            }
        }
    }

    private fun accessPermissions(kind: String): Set<String> {
        val perms = mutableSetOf("android.permission.health.READ_HEALTH_DATA_HISTORY")
        if (kind != "cycle") {
            perms.add(HealthPermission.getReadPermission(SleepSessionRecord::class))
        }
        if (kind != "sleep") {
            perms.add(HealthPermission.getReadPermission(MenstruationFlowRecord::class))
        }
        return perms
    }

    private fun requireClient(): HealthConnectClient {
        val status = HealthConnectClient.getSdkStatus(context)
        if (status != HealthConnectClient.SDK_AVAILABLE) {
            throw IllegalStateException("Health Connect is not available on this phone")
        }
        return HealthConnectClient.getOrCreate(context)
    }

    private suspend fun requirePermission(client: HealthConnectClient, permission: String) {
        val granted = client.permissionController.getGrantedPermissions()
        if (permission !in granted) {
            throw SecurityException("Health Connect permission was not granted")
        }
    }

    private fun timeWindow(call: PluginCall): Pair<Instant, Instant> {
        val end = Instant.now()
        val floor = Instant.parse("2015-01-01T00:00:00Z")
        val since = call.getString("since")?.trim().orEmpty()
        val start = if (since.isNotEmpty()) {
            try {
                Instant.parse(since)
            } catch (_: Exception) {
                java.time.LocalDate.parse(since.take(10))
                    .atStartOfDay(java.time.ZoneId.systemDefault())
                    .toInstant()
            }
        } else {
            val days = (call.getInt("days") ?: 14).coerceIn(1, 4000)
            end.minus(days.toLong(), ChronoUnit.DAYS)
        }
        val bounded = if (start.isBefore(floor)) floor else start
        return (if (bounded.isAfter(end)) end else bounded) to end
    }

    private suspend fun <T : Record> readAll(
        client: HealthConnectClient,
        type: KClass<T>,
        start: Instant,
        end: Instant,
    ): List<Record> {
        val all = mutableListOf<Record>()
        var token: String? = null
        do {
            val response = client.readRecords(
                ReadRecordsRequest(
                    recordType = type,
                    timeRangeFilter = TimeRangeFilter.between(start, end),
                    pageSize = 1000,
                    pageToken = token,
                )
            )
            all.addAll(response.records)
            token = response.pageToken
        } while (!token.isNullOrEmpty())
        return all
    }

    private fun flowLabel(flow: Int): String? {
        return when (flow) {
            4 -> "spotting"
            1 -> "light"
            2 -> "medium"
            3 -> "heavy"
            else -> null
        }
    }

    companion object {
        private const val TAG = "UbetraHealthConnect"
    }
}
