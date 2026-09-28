package org.duckdns.ubeneeko.edgeguard

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.net.VpnService
import android.util.Log

/**
 * Restarts the DNS filter after reboot or app update when Edge Guard was left on.
 */
class EdgeGuardBootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        val action = intent?.action ?: return
        if (
            action != Intent.ACTION_BOOT_COMPLETED &&
            action != Intent.ACTION_MY_PACKAGE_REPLACED
        ) {
            return
        }
        if (!EdgeGuardPrefs.isEnabled(context)) return
        if (EdgeGuardPrefs.getDomains(context).isEmpty()) return
        if (VpnService.prepare(context) != null) {
            Log.w("Ubetra.EdgeGuard", "Boot: VPN permission missing, leave disabled until user opens app")
            return
        }
        EdgeGuardVpnService.start(context)
    }
}
