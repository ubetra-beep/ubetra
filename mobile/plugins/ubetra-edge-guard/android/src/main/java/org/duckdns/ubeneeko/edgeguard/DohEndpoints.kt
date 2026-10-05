package org.duckdns.ubeneeko.edgeguard

/**
 * Domains used by browsers (especially Edge) for DNS-over-HTTPS / Secure DNS.
 * Blocking these forces fallback to system DNS, which Edge Guard intercepts —
 * closing the Edge long-press "Preview page" bypass.
 */
object DohEndpoints {
    val DEFAULT: Set<String> = setOf(
        "cloudflare-dns.com",
        "mozilla.cloudflare-dns.com",
        "one.one.one.one",
        "1dot1dot1dot1.cloudflare-dns.com",
        "dns.google",
        "dns.google.com",
        "dns.quad9.net",
        "dns.nextdns.io",
        "dns.adguard.com",
        "dns-family.adguard.com",
        "dns.msftncsi.com",
        "doh.dns.microsoft.com",
        "chrome.cloudflare-dns.com",
    )
}
