package org.duckdns.ubeneeko.app

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.media.AudioAttributes
import android.os.Build
import android.os.Bundle
import androidx.core.app.NotificationManagerCompat
import com.getcapacitor.BridgeActivity

/**
 * Creates high-importance channels used by FCM:
 * - ubetra_chat: normal chat / activity alerts
 * - ubetra_calls: future incoming calls — can bypass DND once the user grants
 *   Notification Policy Access (Do Not Disturb access) for this app.
 */
class MainActivity : BridgeActivity() {
  override fun onCreate(savedInstanceState: Bundle?) {
    super.onCreate(savedInstanceState)
    createChannels()
  }

  private fun createChannels() {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
    val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
    val attrs = AudioAttributes.Builder()
      .setUsage(AudioAttributes.USAGE_NOTIFICATION_RINGTONE)
      .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
      .build()

    val chat = NotificationChannel(
      "ubetra_chat",
      "Chat",
      NotificationManager.IMPORTANCE_HIGH
    ).apply {
      description = "Partner chat and activity alerts"
      enableVibration(true)
      setShowBadge(true)
    }

    val calls = NotificationChannel(
      "ubetra_calls",
      "Calls",
      NotificationManager.IMPORTANCE_HIGH
    ).apply {
      description = "Incoming calls — can bypass Do Not Disturb after you grant access"
      enableVibration(true)
      setSound(android.provider.Settings.System.DEFAULT_RINGTONE_URI, attrs)
      setBypassDnd(true)
      lockscreenVisibility = android.app.Notification.VISIBILITY_PUBLIC
    }

    manager.createNotificationChannel(chat)
    manager.createNotificationChannel(calls)
  }
}
