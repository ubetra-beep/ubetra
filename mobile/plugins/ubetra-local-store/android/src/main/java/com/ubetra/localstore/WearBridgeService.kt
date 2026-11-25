package com.ubetra.localstore

import android.content.Context
import android.util.Log
import com.google.android.gms.wearable.MessageEvent
import com.google.android.gms.wearable.PutDataMapRequest
import com.google.android.gms.wearable.Wearable
import com.google.android.gms.wearable.WearableListenerService
import org.json.JSONObject
import java.security.SecureRandom

/**
 * Phone side of the watch relay. The watch sends a pairing code, then only
 * AES-GCM payloads. Replies never include the account token.
 */
class WearBridgeService : WearableListenerService() {
    override fun onMessageReceived(event: MessageEvent) {
        if (event.path != PATH_REQ) return
        val text = event.data.toString(Charsets.UTF_8)
        val nodeId = event.sourceNodeId
        Thread {
            try {
                val reply = WearBridge.handle(applicationContext, text, nodeId)
                if (reply != null) {
                    Wearable.getMessageClient(applicationContext)
                        .sendMessage(nodeId, PATH_RES, reply.toByteArray(Charsets.UTF_8))
                }
            } catch (err: Exception) {
                Log.w(TAG, "Wear message was not applied")
            }
        }.start()
    }

    companion object {
        private const val TAG = "UbetraWearBridge"
        const val PATH_REQ = "/ubetra/req"
        const val PATH_RES = "/ubetra/res"
        const val PATH_SUMMARY = "/ubetra/summary"
    }
}

object WearBridge {
    private const val ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

    fun startPairing(context: Context): JSONObject {
        val store = LocalStore.get(context)
        val code = buildString {
            val random = SecureRandom()
            repeat(8) { append(ALPHABET[random.nextInt(ALPHABET.length)]) }
        }
        store.setPairCode(code)
        return JSONObject()
            .put("code", code.substring(0, 4) + "-" + code.substring(4))
            .put("expires_in", 300)
    }

    fun forget(context: Context) {
        val store = LocalStore.get(context)
        store.secrets().setWearKey(null)
        store.secrets().setWearNode("")
        store.clearPairCode()
    }

    fun status(context: Context): JSONObject {
        val secrets = LocalStore.get(context).secrets()
        return JSONObject()
            .put("paired", secrets.wearKey() != null && secrets.wearNode().isNotBlank())
            .put("nodeId", secrets.wearNode())
    }

    fun handle(context: Context, raw: String, nodeId: String): String? {
        val store = LocalStore.get(context)
        val incoming = if (WearCrypto.looksEncrypted(raw)) {
            val key = store.secrets().wearKey() ?: return null
            JSONObject(WearCrypto.decrypt(key, raw).toString(Charsets.UTF_8))
        } else {
            JSONObject(raw)
        }
        val type = incoming.optString("type")
        val id = incoming.optString("id")
        if (type == "pair") {
            return pair(store, incoming, nodeId, id)
        }
        val key = store.secrets().wearKey() ?: return null
        if (store.secrets().wearNode().isNotBlank() && store.secrets().wearNode() != nodeId) {
            return encrypt(key, JSONObject().put("id", id).put("type", "result").put("ok", false).put("text", "Open phone"))
        }
        store.secrets().setWearNode(nodeId)
        val result = when (type) {
            "summary" -> JSONObject().put("id", id).put("type", "result").put("ok", true).put("summary", store.watchSummaryJson())
            "action" -> applyAction(store, incoming, id)
            else -> JSONObject().put("id", id).put("type", "result").put("ok", false).put("text", "Unknown request")
        }
        publishSummary(context)
        Thread {
            try {
                if (store.getServerConfig().optBoolean("serverConfigured")) SyncEngine(context).pushPull()
            } catch (_: Exception) {
            }
        }.start()
        return encrypt(key, result)
    }

    fun publishSummary(context: Context) {
        val store = LocalStore.get(context)
        val key = store.secrets().wearKey() ?: return
        val envelope = WearCrypto.encrypt(key, store.watchSummaryJson().toString().toByteArray(Charsets.UTF_8))
        val request = PutDataMapRequest.create(WearBridgeService.PATH_SUMMARY).apply {
            dataMap.putString("envelope", envelope)
            dataMap.putLong("ts", System.currentTimeMillis())
        }.asPutDataRequest().setUrgent()
        Wearable.getDataClient(context).putDataItem(request)
    }

    private fun pair(store: LocalStore, incoming: JSONObject, nodeId: String, id: String): String? {
        val code = incoming.optString("code").uppercase().filter { it.isLetterOrDigit() }
        if (!store.pairCodeMatches(code)) {
            return JSONObject().put("id", id).put("type", "pair_denied").put("text", "Code was not accepted").toString()
        }
        var key = store.secrets().wearKey()
        if (key == null) {
            key = WearCrypto.generateKey()
            store.secrets().setWearKey(key)
        }
        store.secrets().setWearNode(nodeId)
        store.clearPairCode()
        return JSONObject()
            .put("id", id)
            .put("type", "pair_ok")
            .put("key", android.util.Base64.encodeToString(key, android.util.Base64.NO_WRAP))
            .toString()
    }

    private fun applyAction(store: LocalStore, incoming: JSONObject, id: String): JSONObject {
        val action = incoming.optString("action")
        val clientId = incoming.optString("client_event_id").ifBlank { java.util.UUID.randomUUID().toString() }
        if (action.startsWith("log_")) {
            val body = JSONObject()
                .put("action", action)
                .put("client_event_id", clientId)
                .put("event_type", if (action == "log_play") "no_orgasm" else "orgasm")
                .put("notes", "")
            if (action != "log_play") {
                val tag = when (action) {
                    "log_ruined" -> "Ruined Orgasm"
                    "log_denied" -> "Denied"
                    else -> "Full Orgasm"
                }
                body.put("orgasms", org.json.JSONArray().put(JSONObject().put("tags", org.json.JSONArray().put(tag))))
            }
            store.logOrgasm(body)
        } else {
            store.chastityAction(JSONObject().put("action", action).put("client_event_id", clientId))
        }
        return JSONObject()
            .put("id", id)
            .put("type", "result")
            .put("ok", true)
            .put("text", "Done")
            .put("summary", store.watchSummaryJson())
    }

    private fun encrypt(key: ByteArray, json: JSONObject): String {
        return WearCrypto.encrypt(key, json.toString().toByteArray(Charsets.UTF_8))
    }
}
