package org.duckdns.ubeneeko.edgeguard

/**
 * Minimal DNS packet helpers for A/AAAA query inspection and NXDOMAIN replies.
 */
object DnsPacket {

    data class Query(
        val transactionId: Int,
        val domain: String,
        val questionOffset: Int,
        val questionLength: Int,
    )

    fun parseQuery(udpPayload: ByteArray): Query? {
        if (udpPayload.size < 12) return null

        val flags = ((udpPayload[2].toInt() and 0xFF) shl 8) or (udpPayload[3].toInt() and 0xFF)
        val isResponse = (flags and 0x8000) != 0
        if (isResponse) return null

        val qdCount = ((udpPayload[4].toInt() and 0xFF) shl 8) or (udpPayload[5].toInt() and 0xFF)
        if (qdCount < 1) return null

        val labels = mutableListOf<String>()
        var index = 12
        while (index < udpPayload.size) {
            val len = udpPayload[index].toInt() and 0xFF
            if (len == 0) {
                index++
                break
            }
            if ((len and 0xC0) == 0xC0) return null
            if (index + 1 + len > udpPayload.size) return null
            labels += String(udpPayload, index + 1, len, Charsets.US_ASCII)
            index += 1 + len
        }

        if (index + 4 > udpPayload.size) return null
        val questionLength = index + 4 - 12
        val domain = labels.joinToString(".")
        val txId = ((udpPayload[0].toInt() and 0xFF) shl 8) or (udpPayload[1].toInt() and 0xFF)
        return Query(txId, domain, 12, questionLength)
    }

    fun buildNxDomain(queryPacket: ByteArray): ByteArray {
        val parsed = parseQuery(queryPacket) ?: return emptyNxDomain(queryPacket)
        val questionEnd = parsed.questionOffset + parsed.questionLength
        val out = ByteArray(questionEnd)
        System.arraycopy(queryPacket, 0, out, 0, questionEnd)

        // Flags: response + recursion available + NXDOMAIN (RCODE=3)
        out[2] = 0x81.toByte()
        out[3] = 0x83.toByte()
        out[6] = 0
        out[7] = 0
        out[8] = 0
        out[9] = 0
        out[10] = 0
        out[11] = 0
        return out
    }

    private fun emptyNxDomain(queryPacket: ByteArray): ByteArray {
        if (queryPacket.size < 12) return ByteArray(0)
        val out = queryPacket.copyOf(12)
        out[2] = 0x81.toByte()
        out[3] = 0x83.toByte()
        for (i in 4..11) out[i] = 0
        return out
    }
}
