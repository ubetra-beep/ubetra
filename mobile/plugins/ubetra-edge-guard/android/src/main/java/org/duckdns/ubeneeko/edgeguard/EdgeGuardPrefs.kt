package org.duckdns.ubeneeko.edgeguard

import android.content.Context

/**
 * Persists Edge Guard enable flag and website blocklist for the DNS VPN.
 */
object EdgeGuardPrefs {
    private const val PREFS = "ubetra_edge_guard"
    private const val KEY_ENABLED = "enabled"
    private const val KEY_DOMAINS = "domains"

    private fun prefs(context: Context) =
        context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun isEnabled(context: Context): Boolean =
        prefs(context).getBoolean(KEY_ENABLED, false)

    fun setEnabled(context: Context, enabled: Boolean) {
        prefs(context).edit().putBoolean(KEY_ENABLED, enabled).apply()
    }

    fun getDomains(context: Context): Set<String> {
        val raw = prefs(context).getStringSet(KEY_DOMAINS, emptySet()) ?: emptySet()
        return DomainMatcher.normalizeAll(raw)
    }

    fun setDomains(context: Context, domains: Collection<String>) {
        val normalized = DomainMatcher.normalizeAll(domains)
        prefs(context).edit().putStringSet(KEY_DOMAINS, normalized).apply()
    }

    fun addDomain(context: Context, domain: String): Set<String> {
        val next = getDomains(context).toMutableSet()
        val n = DomainMatcher.normalize(domain)
        if (n.isNotEmpty()) next.add(n)
        setDomains(context, next)
        return next
    }

    fun removeDomain(context: Context, domain: String): Set<String> {
        val n = DomainMatcher.normalize(domain)
        val next = getDomains(context).toMutableSet()
        next.remove(n)
        setDomains(context, next)
        return next
    }

    /** Domains actually filtered: user list + DoH endpoints when non-empty. */
    fun effectiveBlocklist(context: Context): Set<String> {
        val user = getDomains(context)
        if (user.isEmpty()) return emptySet()
        return DomainMatcher.normalizeAll(user + DohEndpoints.DEFAULT)
    }
}
