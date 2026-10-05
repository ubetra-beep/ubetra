package org.duckdns.ubeneeko.edgeguard

/**
 * Matches hostnames against a blocklist with exact and parent-domain rules.
 * Blocking `reddit.com` also blocks `www.reddit.com` and `old.reddit.com`.
 */
object DomainMatcher {

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

    fun isBlocked(queryHost: String, blockedDomains: Set<String>): Boolean {
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
