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

    /** True when the DNS header says the UDP answer was truncated. */
    fun isTruncated(message: ByteArray): Boolean {
        if (message.size < 3) return false
        return (message[2].toInt() and 0x02) != 0
    }

    /**
     * Fit a DNS answer into one UDP packet and clear the truncated bit.
     * Clients otherwise open TCP to the VPN DNS address, which this filter does not serve.
     */
    fun fitForUdp(message: ByteArray, maxSize: Int): ByteArray {
        if (message.size < 12 || maxSize < 12) return message
        if (message.size <= maxSize && !isTruncated(message)) return message

        val questionEnd = endOfQuestions(message) ?: return clearTruncated(message.copyOf(minOf(message.size, maxSize)))
        if (questionEnd > maxSize) return clearTruncated(message.copyOf(maxSize))

        val answerCount = u16(message, 6)
        var offset = questionEnd
        var kept = 0
        var end = questionEnd
        for (i in 0 until answerCount) {
            val next = skipRecord(message, offset) ?: break
            if (next > maxSize) break
            offset = next
            end = next
            kept++
        }
        val out = clearTruncated(message.copyOf(end))
        putU16(out, 6, kept)
        putU16(out, 8, 0)
        putU16(out, 10, 0)
        return out
    }

    private fun clearTruncated(message: ByteArray): ByteArray {
        if (message.size < 3) return message
        message[2] = (message[2].toInt() and 0xFD).toByte()
        return message
    }

    private fun endOfQuestions(message: ByteArray): Int? {
        val count = u16(message, 4)
        var offset = 12
        for (i in 0 until count) {
            offset = skipName(message, offset) ?: return null
            if (offset + 4 > message.size) return null
            offset += 4
        }
        return offset
    }

    private fun skipRecord(message: ByteArray, start: Int): Int? {
        var offset = skipName(message, start) ?: return null
        if (offset + 10 > message.size) return null
        val rdLength = u16(message, offset + 8)
        offset += 10 + rdLength
        if (offset > message.size) return null
        return offset
    }

    private fun skipName(message: ByteArray, start: Int): Int? {
        var offset = start
        var jumps = 0
        while (offset < message.size && jumps < 16) {
            val len = message[offset].toInt() and 0xFF
            if (len == 0) return offset + 1
            if ((len and 0xC0) == 0xC0) {
                if (offset + 1 >= message.size) return null
                return offset + 2
            }
            if (offset + 1 + len > message.size) return null
            offset += 1 + len
            jumps++
        }
        return null
    }

    private fun u16(buf: ByteArray, offset: Int): Int {
        if (offset + 1 >= buf.size) return 0
        return ((buf[offset].toInt() and 0xFF) shl 8) or (buf[offset + 1].toInt() and 0xFF)
    }

    private fun putU16(buf: ByteArray, offset: Int, value: Int) {
        buf[offset] = (value ushr 8).toByte()
        buf[offset + 1] = (value and 0xFF).toByte()
    }
}
