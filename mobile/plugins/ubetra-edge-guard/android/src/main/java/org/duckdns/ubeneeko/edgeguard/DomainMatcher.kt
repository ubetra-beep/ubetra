package org.duckdns.ubeneeko.edgeguard

/**
 * Matches hostnames against a blocklist with exact and parent-domain rules.
 * Blocking `reddit.com` also blocks `www.reddit.com` and `old.reddit.com`.
 */
object DomainMatcher {

    /**
     * Hosts Google Drive needs in order to sign in and upload.
     * These stay reachable even if a parent such as google.com is blocked.
     */
    private val UPLOAD_ALLOW = setOf(
        "googleapis.com",
        "drive.google.com",
        "docs.google.com",
        "drive.usercontent.google.com",
        "clients.google.com",
        "clients6.google.com",
        "accounts.google.com",
        "ssl.gstatic.com",
        "www.gstatic.com",
    )

    fun normalize(host: String): String {
        return host.trim()
            .lowercase()
            .removePrefix("http://")
            .removePrefix("https://")
            .substringBefore('/')
            .substringBefore('?')
            .substringBefore(':')
            .removePrefix("www.")
            .trim('.')
    }

    fun normalizeAll(hosts: Iterable<String>): Set<String> {
        val out = HashSet<String>()
        for (host in hosts) {
            val n = normalize(host)
            if (n.isNotEmpty()) out.add(n)
        }
        return out
    }

    fun allowsUpload(queryHost: String): Boolean {
        var host = normalize(queryHost)
        while (host.isNotEmpty()) {
            if (host in UPLOAD_ALLOW) return true
            val dot = host.indexOf('.')
            if (dot < 0) return false
            host = host.substring(dot + 1)
        }
        return false
    }

    fun isBlocked(queryHost: String, blockedDomains: Set<String>): Boolean {
        if (allowsUpload(queryHost)) return false
        if (blockedDomains.isEmpty()) return false
        var host = normalize(queryHost)
        if (host.isEmpty()) return false

        while (true) {
            if (host in blockedDomains) return true
            val dot = host.indexOf('.')
            if (dot < 0) return false
            host = host.substring(dot + 1)
            if (host.isEmpty()) return false
        }
    }
}
