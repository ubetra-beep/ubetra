package org.duckdns.ubeneeko.edgeguard

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

class DnsPacketTest {
    @Test
    fun parseQuery_and_nxdomain() {
        // Minimal DNS query for example.com A
        val query = byteArrayOf(
            0x12, 0x34, // id
            0x01, 0x00, // flags
            0x00, 0x01, // qdcount
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            7, 'e'.code.toByte(), 'x'.code.toByte(), 'a'.code.toByte(), 'm'.code.toByte(),
            'p'.code.toByte(), 'l'.code.toByte(), 'e'.code.toByte(),
            3, 'c'.code.toByte(), 'o'.code.toByte(), 'm'.code.toByte(),
            0,
            0x00, 0x01, // type A
            0x00, 0x01, // class IN
        )
        val parsed = DnsPacket.parseQuery(query)
        assertNotNull(parsed)
        assertEquals("example.com", parsed!!.domain)
        assertEquals(0x1234, parsed.transactionId)

        val nx = DnsPacket.buildNxDomain(query)
        assertTrue(nx.size >= 12)
        assertEquals(0x81.toByte(), nx[2])
        assertEquals(0x83.toByte(), nx[3])
    }
}
