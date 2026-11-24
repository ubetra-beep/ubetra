package com.ubetra.localstore

import com.getcapacitor.JSObject
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.CapacitorPlugin
import org.json.JSONObject

@CapacitorPlugin(name = "UbetraLocalStore")
class UbetraLocalStorePlugin : Plugin() {
    override fun load() {
        super.load()
        SyncScheduler.ensure(context)
    }

    @PluginMethod
    fun getServerConfig(call: PluginCall) {
        call.resolve(js(LocalStore.get(context).getServerConfig()))
    }

    @PluginMethod
    fun getStatus(call: PluginCall) {
        call.resolve(js(LocalStore.get(context).status()))
    }

    @PluginMethod
    fun listRecent(call: PluginCall) {
        call.resolve(js(LocalStore.get(context).listRecent()))
    }

    @PluginMethod
    fun logOrgasm(call: PluginCall) {
        try {
            val created = LocalStore.get(context).logOrgasm(payload(call))
            WearBridge.publishSummary(context)
            SyncScheduler.enqueueSoon(context)
            call.resolve(js(created))
        } catch (err: Exception) {
            call.reject(err.message ?: "Could not save")
        }
    }

    @PluginMethod
    fun chastityAction(call: PluginCall) {
        try {
            val status = LocalStore.get(context).chastityAction(payload(call))
            WearBridge.publishSummary(context)
            SyncScheduler.enqueueSoon(context)
            call.resolve(js(status))
        } catch (err: Exception) {
            call.reject(err.message ?: "Could not save")
        }
    }

    @PluginMethod
    fun enqueueSync(call: PluginCall) {
        SyncScheduler.enqueueSoon(context)
        call.resolve(JSObject().put("started", true))
    }

    @PluginMethod
    fun syncNow(call: PluginCall) {
        try {
            val engine = SyncEngine(context)
            if (!engine.configured()) {
                call.resolve(JSObject().put("ok", false).put("reason", "phone-only"))
                return
            }
            val reachable = engine.probe()
            if (!reachable) {
                call.resolve(JSObject().put("ok", false).put("reason", "offline"))
                return
            }
            call.resolve(js(engine.pushPull().put("ok", true)))
        } catch (err: Exception) {
            call.reject(err.message ?: "Sync failed")
        }
    }

    @PluginMethod
    fun probeServer(call: PluginCall) {
        val reachable = SyncEngine(context).probe()
        call.resolve(JSObject().put("reachable", reachable))
    }

    @PluginMethod
    fun setServerUrl(call: PluginCall) {
        try {
            val url = call.getString("url").orEmpty()
            call.resolve(js(LocalStore.get(context).setServerUrl(url)))
        } catch (err: Exception) {
            call.reject(err.message ?: "Server must be an http(s) URL")
        }
    }

    @PluginMethod
    fun setPhoneOnly(call: PluginCall) {
        call.resolve(js(LocalStore.get(context).setPhoneOnly()))
    }

    @PluginMethod
    fun setSession(call: PluginCall) {
        LocalStore.get(context).setSession(
            token = call.getString("token").orEmpty(),
            dynamicId = call.getString("dynamicId").orEmpty(),
            membershipId = call.getString("membershipId").orEmpty(),
            apiBase = call.getString("apiBase").orEmpty(),
            dynamicJson = call.getString("dynamicJson").orEmpty(),
            userJson = call.getString("userJson").orEmpty(),
        )
        SyncScheduler.enqueueSoon(context)
        call.resolve(JSObject().put("ok", true))
    }

    @PluginMethod
    fun startWatchPairing(call: PluginCall) {
        call.resolve(js(WearBridge.startPairing(context)))
    }

    @PluginMethod
    fun watchStatus(call: PluginCall) {
        call.resolve(js(WearBridge.status(context)))
    }

    @PluginMethod
    fun forgetWatch(call: PluginCall) {
        WearBridge.forget(context)
        call.resolve(JSObject().put("ok", true))
    }

    @PluginMethod
    fun showServerSetup(call: PluginCall) {
        val local = bridge.localUrl ?: "https://localhost/"
        activity.runOnUiThread {
            bridge.webView.loadUrl(local)
        }
        call.resolve(JSObject().put("ok", true))
    }

    @PluginMethod
    fun openServer(call: PluginCall) {
        val url = call.getString("url").orEmpty().ifBlank { LocalStore.get(context).apiBase() }
        if (url.isBlank()) {
            call.reject("No server URL")
            return
        }
        activity.runOnUiThread { bridge.webView.loadUrl(url) }
        call.resolve(JSObject().put("ok", true))
    }

    private fun payload(call: PluginCall): JSONObject {
        val raw = call.getString("payload")
        if (!raw.isNullOrBlank()) return JSONObject(raw)
        return JSONObject()
    }

    private fun js(json: JSONObject): JSObject = JSObject(json.toString())
}
