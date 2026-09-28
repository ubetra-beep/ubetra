package org.duckdns.ubeneeko.edgeguard

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.VpnService
import android.os.Build
import android.os.ParcelFileDescriptor
import android.util.Log
import androidx.core.app.NotificationCompat
import java.io.FileInputStream
import java.io.FileOutputStream
import java.io.IOException
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

/**
 * Local VPN that intercepts DNS only and NXDOMAINs blocked websites.
 * Also blocks common DNS-over-HTTPS endpoints so Edge Preview cannot bypass.
 */
class EdgeGuardVpnService : VpnService() {

    companion object {
        private const val TAG = "Ubetra.EdgeGuardVpn"
        private const val VPN_ADDRESS = "10.55.55.1"
        private const val VPN_DNS = "10.55.55.10"
        private const val VPN_ADDRESS_V6 = "fd55:5555::1"
        private const val VPN_DNS_V6 = "fd55:5555::10"
        private const val UPSTREAM_DNS = "1.1.1.1"
        private const val NOTIFICATION_ID = 55441
        private const val CHANNEL_ID = "ubetra_edge_guard"
        const val ACTION_START = "org.duckdns.ubeneeko.edgeguard.START"
        const val ACTION_STOP = "org.duckdns.ubeneeko.edgeguard.STOP"
        const val ACTION_RELOAD = "org.duckdns.ubeneeko.edgeguard.RELOAD"

        @Volatile
        var isRunning: Boolean = false
            private set

        fun start(context: Context) {
            val intent = Intent(context, EdgeGuardVpnService::class.java).setAction(ACTION_START)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun stop(context: Context) {
            context.startService(
                Intent(context, EdgeGuardVpnService::class.java).setAction(ACTION_STOP)
            )
        }

        fun reload(context: Context) {
            if (!EdgeGuardPrefs.isEnabled(context)) {
                stop(context)
                return
            }
            if (prepare(context) != null) {
                Log.w(TAG, "reload: VPN permission not granted yet")
                return
            }
            val intent = Intent(context, EdgeGuardVpnService::class.java).setAction(ACTION_RELOAD)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }
    }

    private val vpnThread = AtomicReference<Thread?>(null)
    private val loopRunning = AtomicBoolean(false)
    private var vpnInterface: ParcelFileDescriptor? = null
    private var blockedDomains: Set<String> = emptySet()

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                stopAndDispose()
                return START_NOT_STICKY
            }
            ACTION_RELOAD, ACTION_START, null -> {
                if (!EdgeGuardPrefs.isEnabled(this)) {
                    stopAndDispose()
                    return START_NOT_STICKY
                }
                blockedDomains = EdgeGuardPrefs.effectiveBlocklist(this)
                if (blockedDomains.isEmpty()) {
                    Log.w(TAG, "No domains to block; stopping")
                    stopAndDispose()
                    return START_NOT_STICKY
                }
                startFg()
                reconnect()
                return START_STICKY
            }
            else -> {
                stopAndDispose()
                return START_NOT_STICKY
            }
        }
    }

    private fun startFg() {
        ensureChannel()
        val launch = packageManager.getLaunchIntentForPackage(packageName)
        val pending = PendingIntent.getActivity(
            this,
            0,
            launch,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val notification: Notification = NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Edge Guard")
            .setContentText("Blocking ${EdgeGuardPrefs.getDomains(this).size} website(s) via DNS")
            .setSmallIcon(android.R.drawable.ic_lock_lock)
            .setContentIntent(pending)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .build()
        startForeground(NOTIFICATION_ID, notification)
        isRunning = true
    }

    private fun ensureChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = getSystemService(NotificationManager::class.java) ?: return
        val channel = NotificationChannel(
            CHANNEL_ID,
            "Edge Guard",
            NotificationManager.IMPORTANCE_LOW
        ).apply {
            description = "DNS website blocking is active"
        }
        manager.createNotificationChannel(channel)
    }

    private fun reconnect() {
        disconnect()
        blockedDomains = EdgeGuardPrefs.effectiveBlocklist(this)
        if (blockedDomains.isEmpty() || !EdgeGuardPrefs.isEnabled(this)) {
            stopAndDispose()
            return
        }
        val thread = Thread(dnsFilterRunnable, TAG)
        vpnThread.getAndSet(thread)?.interrupt()
        thread.start()
    }

    private val dnsFilterRunnable = Runnable {
        try {
            val builder = Builder()
                .setSession("UBETRA Edge Guard")
                .setMtu(1500)
                .addAddress(VPN_ADDRESS, 32)
                .addDnsServer(VPN_DNS)
                .addRoute(VPN_DNS, 32)
                .addAddress(VPN_ADDRESS_V6, 128)
                .addDnsServer(VPN_DNS_V6)
                .addRoute(VPN_DNS_V6, 128)
                .setBlocking(true)

            try {
                builder.addDisallowedApplication(packageName)
            } catch (_: PackageManager.NameNotFoundException) {
            }

            val pfd = builder.establish()
            if (pfd == null) {
                Log.e(TAG, "Failed to establish VPN interface")
                stopAndDispose()
                return@Runnable
            }
            vpnInterface = pfd
            Log.i(TAG, "DNS filter active, domains=${blockedDomains.size}")
            loopRunning.set(true)
            packetLoop(pfd)
        } catch (e: Exception) {
            Log.e(TAG, "VPN connection failed", e)
            stopAndDispose()
        }
    }

    private fun packetLoop(pfd: ParcelFileDescriptor) {
        val input = FileInputStream(pfd.fileDescriptor)
        val output = FileOutputStream(pfd.fileDescriptor)
        val packet = ByteArray(32767)

        while (loopRunning.get()) {
            val length = try {
                input.read(packet)
            } catch (_: Exception) {
                break
            }
            if (length <= 0) continue
            try {
                handleIpPacket(packet, length, output)
            } catch (e: Exception) {
                Log.w(TAG, "packet handling error", e)
            }
        }
    }

    private fun handleIpPacket(packet: ByteArray, length: Int, output: FileOutputStream) {
        if (length < 20) return
        when ((packet[0].toInt() ushr 4) and 0xF) {
            4 -> handleIpv4(packet, length, output)
            6 -> handleIpv6(packet, length, output)
        }
    }

    private fun handleIpv4(packet: ByteArray, length: Int, output: FileOutputStream) {
        val headerLength = (packet[0].toInt() and 0x0F) * 4
        if (length < headerLength + 8) return
        if ((packet[9].toInt() and 0xFF) != 17) return

        val srcPort = u16(packet, headerLength)
        val dstPort = u16(packet, headerLength + 2)
        if (dstPort != 53) return

        val udpLength = u16(packet, headerLength + 4)
        val dnsOffset = headerLength + 8
        val dnsLength = minOf(udpLength - 8, length - dnsOffset)
        if (dnsLength <= 0) return

        val dnsQuery = packet.copyOfRange(dnsOffset, dnsOffset + dnsLength)
        val dnsResponse = resolveDns(dnsQuery) ?: return
        output.write(buildIpv4UdpResponse(packet, srcPort, dnsResponse))
        output.flush()
    }

    private fun handleIpv6(packet: ByteArray, length: Int, output: FileOutputStream) {
        if (length < 48) return
        if ((packet[6].toInt() and 0xFF) != 17) return

        val srcPort = u16(packet, 40)
        val dstPort = u16(packet, 42)
        if (dstPort != 53) return

        val udpLength = u16(packet, 44)
        val dnsOffset = 48
        val dnsLength = minOf(udpLength - 8, length - dnsOffset)
        if (dnsLength <= 0) return

        val dnsQuery = packet.copyOfRange(dnsOffset, dnsOffset + dnsLength)
        val dnsResponse = resolveDns(dnsQuery) ?: return
        output.write(buildIpv6UdpResponse(packet, srcPort, dnsResponse))
        output.flush()
    }

    private fun resolveDns(dnsQuery: ByteArray): ByteArray? {
        val query = DnsPacket.parseQuery(dnsQuery) ?: return forwardDns(dnsQuery)
        if (DomainMatcher.isBlocked(query.domain, blockedDomains)) {
            Log.i(TAG, "Blocked ${query.domain}")
            return DnsPacket.buildNxDomain(dnsQuery)
        }
        return forwardDns(dnsQuery)
    }

    private fun forwardDns(dnsQuery: ByteArray): ByteArray? {
        var socket: DatagramSocket? = null
        return try {
            socket = DatagramSocket()
            protect(socket)
            socket.soTimeout = 3000
            val upstream = InetAddress.getByName(UPSTREAM_DNS)
            socket.send(DatagramPacket(dnsQuery, dnsQuery.size, upstream, 53))
            val buffer = ByteArray(4096)
            val response = DatagramPacket(buffer, buffer.size)
            socket.receive(response)
            buffer.copyOf(response.length)
        } catch (e: Exception) {
            Log.w(TAG, "upstream DNS failed", e)
            null
        } finally {
            socket?.close()
        }
    }

    private fun buildIpv4UdpResponse(
        request: ByteArray,
        srcPort: Int,
        dnsResponse: ByteArray,
    ): ByteArray {
        val udpLength = 8 + dnsResponse.size
        val totalLength = 20 + udpLength
        val out = ByteArray(totalLength)

        out[0] = 0x45
        out[2] = (totalLength ushr 8).toByte()
        out[3] = (totalLength and 0xFF).toByte()
        out[6] = 0x40
        out[8] = 64
        out[9] = 17
        System.arraycopy(request, 16, out, 12, 4)
        System.arraycopy(request, 12, out, 16, 4)

        putU16(out, 20, 53)
        putU16(out, 22, srcPort)
        putU16(out, 24, udpLength)
        System.arraycopy(dnsResponse, 0, out, 28, dnsResponse.size)

        putU16(out, 10, ipChecksum(out, 0, 20))
        putU16(out, 26, udpChecksumIpv4(out, 20, udpLength))
        return out
    }

    private fun buildIpv6UdpResponse(
        request: ByteArray,
        srcPort: Int,
        dnsResponse: ByteArray,
    ): ByteArray {
        val udpLength = 8 + dnsResponse.size
        val out = ByteArray(40 + udpLength)
        out[0] = 0x60
        putU16(out, 4, udpLength)
        out[6] = 17
        out[7] = 64
        System.arraycopy(request, 24, out, 8, 16)
        System.arraycopy(request, 8, out, 24, 16)
        putU16(out, 40, 53)
        putU16(out, 42, srcPort)
        putU16(out, 44, udpLength)
        System.arraycopy(dnsResponse, 0, out, 48, dnsResponse.size)
        putU16(out, 46, udpChecksumIpv6(out, 40, udpLength))
        return out
    }

    private fun u16(buf: ByteArray, offset: Int): Int =
        ((buf[offset].toInt() and 0xFF) shl 8) or (buf[offset + 1].toInt() and 0xFF)

    private fun putU16(buf: ByteArray, offset: Int, value: Int) {
        buf[offset] = (value ushr 8).toByte()
        buf[offset + 1] = (value and 0xFF).toByte()
    }

    private fun ipChecksum(buf: ByteArray, offset: Int, length: Int): Int {
        var sum = 0
        var i = offset
        while (i < offset + length) {
            if (i == offset + 10) {
                i += 2
                continue
            }
            sum += u16(buf, i)
            i += 2
        }
        while (sum ushr 16 != 0) sum = (sum and 0xFFFF) + (sum ushr 16)
        return sum.inv() and 0xFFFF
    }

    private fun udpChecksumIpv4(packet: ByteArray, udpOffset: Int, udpLength: Int): Int {
        var sum = 0
        sum += u16(packet, 12) + u16(packet, 14) + u16(packet, 16) + u16(packet, 18)
        sum += 17 + udpLength
        var i = udpOffset
        val end = udpOffset + udpLength
        while (i + 1 < end) {
            if (i != udpOffset + 6) sum += u16(packet, i)
            i += 2
        }
        if (i < end) sum += (packet[i].toInt() and 0xFF) shl 8
        while (sum ushr 16 != 0) sum = (sum and 0xFFFF) + (sum ushr 16)
        val result = sum.inv() and 0xFFFF
        return if (result == 0) 0xFFFF else result
    }

    private fun udpChecksumIpv6(packet: ByteArray, udpOffset: Int, udpLength: Int): Int {
        var sum = 0L
        for (i in 8 until 40 step 2) sum += u16(packet, i).toLong()
        sum += udpLength.toLong() + 17L
        var i = udpOffset
        val end = udpOffset + udpLength
        while (i + 1 < end) {
            if (i != udpOffset + 6) sum += u16(packet, i).toLong()
            i += 2
        }
        if (i < end) sum += ((packet[i].toInt() and 0xFF) shl 8).toLong()
        while (sum ushr 16 != 0L) sum = (sum and 0xFFFF) + (sum ushr 16)
        val result = sum.inv().toInt() and 0xFFFF
        return if (result == 0) 0xFFFF else result
    }

    private fun disconnect() {
        loopRunning.set(false)
        try {
            vpnInterface?.close()
        } catch (_: IOException) {
        }
        vpnInterface = null
        vpnThread.getAndSet(null)?.interrupt()
    }

    private fun stopAndDispose() {
        disconnect()
        isRunning = false
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() {
        disconnect()
        isRunning = false
        super.onDestroy()
    }

    override fun onRevoke() {
        EdgeGuardPrefs.setEnabled(this, false)
        stopAndDispose()
        super.onRevoke()
    }
}
