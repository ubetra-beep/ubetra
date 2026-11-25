package com.ubetra.wear

import android.content.Context
import com.google.android.gms.wearable.CapabilityClient
import com.google.android.gms.wearable.DataEventBuffer
import com.google.android.gms.wearable.DataMapItem
import com.google.android.gms.wearable.MessageEvent
import com.google.android.gms.wearable.Wearable
import com.google.android.gms.wearable.WearableListenerService
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.tasks.await
import kotlinx.coroutines.withTimeout
import org.json.JSONObject
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap

/**
 * Talks only to the paired phone. The first pair message is the code exchange.
 * Everything after that is an AES-GCM envelope.
 */
class WatchPhoneService : WearableListenerService() {
    override fun onMessageReceived(event: MessageEvent) {
        if (event.path != PATH_RES) return
        PhoneRelay.deliver(applicationContext, event.data.toString(Charsets.UTF_8))
    }

    override fun onDataChanged(events: DataEventBuffer) {
        try {
            for (index in 0 until events.count) {
                val item = events.get(index).dataItem
                if (item.uri.path != PATH_SUMMARY) continue
                val envelope = DataMapItem.fromDataItem(item).dataMap.getString("envelope") ?: continue
                PhoneRelay.cacheEnvelope(applicationContext, envelope)
            }
        } finally {
            events.release()
        }
    }
}

object PhoneRelay {
    private val pending = ConcurrentHashMap<String, CompletableDeferred<JSONObject>>()

    fun deliver(context: Context, raw: String) {
        val store = WatchSessionStore(context)
        val json = decode(store, raw) ?: return
        val id = json.optString("id")
        if (json.optString("type") == "pair_ok" || json.optString("type") == "pair_denied") {
            pending.remove(id)?.complete(json)
            return
        }
        if (json.has("summary")) {
            store.writeSummary(json.getJSONObject("summary").toString())
        }
        pending.remove(id)?.complete(json)
    }

    fun cacheEnvelope(context: Context, envelope: String) {
        val store = WatchSessionStore(context)
        val key = store.key() ?: return
        try {
            val plain = WearCrypto.decrypt(key, envelope).toString(Charsets.UTF_8)
            store.writeSummary(plain)
            WatchRepository.get(context).pushSurfaces()
        } catch (_: Exception) {
        }
    }

    suspend fun pair(context: Context, code: String, timeoutMs: Long): JSONObject {
        val body = JSONObject()
            .put("id", UUID.randomUUID().toString())
            .put("type", "pair")
            .put("code", normalizePairCode(code))
        return roundTrip(context, body.toString(), encrypted = false, timeoutMs = timeoutMs)
    }

    suspend fun action(context: Context, action: WatchAction, timeoutMs: Long): JSONObject {
        val body = JSONObject()
            .put("id", UUID.randomUUID().toString())
            .put("type", "action")
            .put("action", action.id)
            .put("client_event_id", UUID.randomUUID().toString())
        return roundTrip(context, body.toString(), encrypted = true, timeoutMs = timeoutMs)
    }

    suspend fun summary(context: Context, timeoutMs: Long): JSONObject {
        val body = JSONObject()
            .put("id", UUID.randomUUID().toString())
            .put("type", "summary")
        val reply = roundTrip(context, body.toString(), encrypted = true, timeoutMs = timeoutMs)
        return reply.optJSONObject("summary") ?: reply
    }

    private suspend fun roundTrip(context: Context, plain: String, encrypted: Boolean, timeoutMs: Long): JSONObject {
        val node = phoneNode(context) ?: throw WatchApiException(0, OPEN_PHONE)
        val store = WatchSessionStore(context)
        val wire = if (!encrypted) {
            plain
        } else {
            val key = store.key() ?: throw WatchSignedOutException()
            WearCrypto.encrypt(key, plain.toByteArray(Charsets.UTF_8))
        }
        val id = JSONObject(plain).optString("id")
        val deferred = CompletableDeferred<JSONObject>()
        pending[id] = deferred
        try {
            Wearable.getMessageClient(context).sendMessage(node, PATH_REQ, wire.toByteArray(Charsets.UTF_8)).await()
            return withTimeout(timeoutMs) { deferred.await() }
        } finally {
            pending.remove(id)
        }
    }

    private suspend fun phoneNode(context: Context): String? {
        val capability = Wearable.getCapabilityClient(context)
            .getCapability(PHONE_CAPABILITY, CapabilityClient.FILTER_REACHABLE)
            .await()
        val fromCap = capability.nodes.firstOrNull { it.isNearby }?.id ?: capability.nodes.firstOrNull()?.id
        if (!fromCap.isNullOrBlank()) return fromCap
        return Wearable.getNodeClient(context).connectedNodes.await().firstOrNull()?.id
    }

    private fun decode(store: WatchSessionStore, raw: String): JSONObject? {
        val trimmed = raw.trim()
        if (trimmed.contains("\"pair_ok\"") || trimmed.contains("\"pair_denied\"")) {
            return try {
                JSONObject(trimmed)
            } catch (_: Exception) {
                null
            }
        }
        val key = store.key() ?: return null
        return try {
            JSONObject(WearCrypto.decrypt(key, trimmed).toString(Charsets.UTF_8))
        } catch (_: Exception) {
            null
        }
    }
}
