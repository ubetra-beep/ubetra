package org.duckdns.ubeneeko.edgeguard

import android.app.Activity
import android.net.VpnService
import androidx.activity.result.ActivityResult
import com.getcapacitor.JSArray
import com.getcapacitor.JSObject
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.ActivityCallback
import com.getcapacitor.annotation.CapacitorPlugin

@CapacitorPlugin(name = "UbetraEdgeGuard")
class UbetraEdgeGuardPlugin : Plugin() {

    companion object {
        private const val VPN_REQUEST = "edgeGuardVpnPermission"
    }

    @PluginMethod
    fun getStatus(call: PluginCall) {
        val domains = EdgeGuardPrefs.getDomains(context).sorted()
        val ret = JSObject()
        ret.put("available", true)
        ret.put("enabled", EdgeGuardPrefs.isEnabled(context))
        ret.put("running", EdgeGuardVpnService.isRunning)
        ret.put("vpnPermissionGranted", VpnService.prepare(context) == null)
        ret.put("domainCount", domains.size)
        ret.put("domains", JSArray(domains))
        call.resolve(ret)
    }

    @PluginMethod
    fun requestVpnPermission(call: PluginCall) {
        val prepare = VpnService.prepare(activity)
        if (prepare == null) {
            val ret = JSObject()
            ret.put("granted", true)
            call.resolve(ret)
            return
        }
        startActivityForResult(call, prepare, VPN_REQUEST)
    }

    @ActivityCallback
    private fun edgeGuardVpnPermission(call: PluginCall, result: ActivityResult) {
        val granted = result.resultCode == Activity.RESULT_OK
        val ret = JSObject()
        ret.put("granted", granted)
        if (granted && EdgeGuardPrefs.isEnabled(context) && EdgeGuardPrefs.getDomains(context).isNotEmpty()) {
            EdgeGuardVpnService.start(context)
        }
        call.resolve(ret)
    }

    @PluginMethod
    fun setEnabled(call: PluginCall) {
        val enabled = call.getBoolean("enabled", false) ?: false
        if (enabled) {
            if (EdgeGuardPrefs.getDomains(context).isEmpty()) {
                call.reject("Add at least one website before enabling Edge Guard")
                return
            }
            val prepare = VpnService.prepare(activity)
            if (prepare != null) {
                EdgeGuardPrefs.setEnabled(context, true)
                startActivityForResult(call, prepare, "edgeGuardEnableWithPermission")
                return
            }
            EdgeGuardPrefs.setEnabled(context, true)
            EdgeGuardVpnService.start(context)
        } else {
            EdgeGuardPrefs.setEnabled(context, false)
            EdgeGuardVpnService.stop(context)
        }
        call.resolve(statusObject())
    }

    @ActivityCallback
    private fun edgeGuardEnableWithPermission(call: PluginCall, result: ActivityResult) {
        val granted = result.resultCode == Activity.RESULT_OK
        if (!granted) {
            EdgeGuardPrefs.setEnabled(context, false)
            val ret = statusObject()
            ret.put("vpnPermissionGranted", false)
            call.resolve(ret)
            return
        }
        EdgeGuardPrefs.setEnabled(context, true)
        EdgeGuardVpnService.start(context)
        call.resolve(statusObject())
    }

    @PluginMethod
    fun getBlockedDomains(call: PluginCall) {
        val domains = EdgeGuardPrefs.getDomains(context).sorted()
        val ret = JSObject()
        ret.put("domains", JSArray(domains))
        call.resolve(ret)
    }

    @PluginMethod
    fun setBlockedDomains(call: PluginCall) {
        val arr = call.getArray("domains") ?: JSArray()
        val list = ArrayList<String>()
        for (i in 0 until arr.length()) {
            val value = when (val raw = arr.get(i)) {
                is String -> raw
                null -> continue
                else -> raw.toString()
            }
            if (value.isNotBlank()) list.add(value)
        }
        EdgeGuardPrefs.setDomains(context, list)
        syncService()
        val ret = JSObject()
        ret.put("domains", JSArray(EdgeGuardPrefs.getDomains(context).sorted()))
        call.resolve(ret)
    }

    @PluginMethod
    fun addBlockedDomain(call: PluginCall) {
        val domain = call.getString("domain")
        if (domain.isNullOrBlank()) {
            call.reject("domain is required")
            return
        }
        val domains = EdgeGuardPrefs.addDomain(context, domain).sorted()
        syncService()
        val ret = JSObject()
        ret.put("domains", JSArray(domains))
        call.resolve(ret)
    }

    @PluginMethod
    fun removeBlockedDomain(call: PluginCall) {
        val domain = call.getString("domain")
        if (domain.isNullOrBlank()) {
            call.reject("domain is required")
            return
        }
        val domains = EdgeGuardPrefs.removeDomain(context, domain).sorted()
        syncService()
        val ret = JSObject()
        ret.put("domains", JSArray(domains))
        call.resolve(ret)
    }

    private fun syncService() {
        if (EdgeGuardPrefs.isEnabled(context) && EdgeGuardPrefs.getDomains(context).isNotEmpty()) {
            if (VpnService.prepare(context) == null) {
                EdgeGuardVpnService.reload(context)
            }
        } else if (EdgeGuardVpnService.isRunning) {
            EdgeGuardVpnService.stop(context)
        }
    }

    private fun statusObject(): JSObject {
        val domains = EdgeGuardPrefs.getDomains(context).sorted()
        val ret = JSObject()
        ret.put("available", true)
        ret.put("enabled", EdgeGuardPrefs.isEnabled(context))
        ret.put("running", EdgeGuardVpnService.isRunning)
        ret.put("vpnPermissionGranted", VpnService.prepare(context) == null)
        ret.put("domainCount", domains.size)
        ret.put("domains", JSArray(domains))
        return ret
    }
}
