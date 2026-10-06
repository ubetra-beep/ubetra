package org.duckdns.ubeneeko.appupdater

import android.app.DownloadManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.Settings
import androidx.activity.result.ActivityResult
import androidx.core.content.FileProvider
import com.getcapacitor.JSObject
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.ActivityCallback
import com.getcapacitor.annotation.CapacitorPlugin
import java.io.File

@CapacitorPlugin(name = "UbetraAppUpdater")
class UbetraAppUpdaterPlugin : Plugin() {

    @PluginMethod
    fun canInstall(call: PluginCall) {
        val ret = JSObject()
        ret.put("canInstall", packageInstallsAllowed())
        call.resolve(ret)
    }

    @PluginMethod
    fun openInstallPermission(call: PluginCall) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O || packageInstallsAllowed()) {
            val ret = JSObject()
            ret.put("canInstall", true)
            call.resolve(ret)
            return
        }
        val intent = Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES)
        intent.data = Uri.parse("package:" + context.packageName)
        startActivityForResult(call, intent, "installPermission")
    }

    @ActivityCallback
    private fun installPermission(call: PluginCall, result: ActivityResult) {
        val ret = JSObject()
        ret.put("canInstall", packageInstallsAllowed())
        call.resolve(ret)
    }

    @PluginMethod
    fun downloadAndInstall(call: PluginCall) {
        val url = call.getString("url")
        if (url.isNullOrBlank()) {
            call.reject("Missing url")
            return
        }
        val dir = context.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS)
        if (dir == null) {
            call.reject("No download directory")
            return
        }
        if (!dir.exists()) dir.mkdirs()
        val apk = File(dir, "ubetra.apk")
        if (apk.exists()) apk.delete()

        val request = DownloadManager.Request(Uri.parse(url))
        request.setMimeType("application/vnd.android.package-archive")
        request.setTitle("ubetra.apk")
        request.setDescription("UBETRA update")
        request.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
        request.setDestinationInExternalFilesDir(context, Environment.DIRECTORY_DOWNLOADS, "ubetra.apk")
        val manager = context.getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager
        val downloadId = manager.enqueue(request)
        call.setKeepAlive(true)
        val started = JSObject()
        started.put("status", "started")
        notifyListeners("progress", started)

        val filter = IntentFilter(DownloadManager.ACTION_DOWNLOAD_COMPLETE)
        val receiver = object : BroadcastReceiver() {
            override fun onReceive(ctx: Context, intent: Intent) {
                val done = intent.getLongExtra(DownloadManager.EXTRA_DOWNLOAD_ID, -1L)
                if (done != downloadId) return
                try {
                    context.unregisterReceiver(this)
                } catch (_: Exception) {
                }
                val cursor = manager.query(DownloadManager.Query().setFilterById(downloadId))
                var success = false
                if (cursor != null && cursor.moveToFirst()) {
                    val statusIdx = cursor.getColumnIndex(DownloadManager.COLUMN_STATUS)
                    success = statusIdx >= 0 && cursor.getInt(statusIdx) == DownloadManager.STATUS_SUCCESSFUL
                }
                cursor?.close()
                if (!success || !apk.exists()) {
                    call.reject("Download failed")
                    return
                }
                val finished = JSObject()
                finished.put("status", "complete")
                notifyListeners("progress", finished)
                openInstaller(apk)
                val ret = JSObject()
                ret.put("installed", true)
                call.resolve(ret)
            }
        }
        if (Build.VERSION.SDK_INT >= 33) {
            context.registerReceiver(receiver, filter, Context.RECEIVER_EXPORTED)
        } else {
            context.registerReceiver(receiver, filter)
        }
    }

    private fun packageInstallsAllowed(): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return true
        return context.packageManager.canRequestPackageInstalls()
    }

    private fun openInstaller(apk: File) {
        val uri = FileProvider.getUriForFile(context, context.packageName + ".fileprovider", apk)
        val view = Intent(Intent.ACTION_VIEW)
        view.setDataAndType(uri, "application/vnd.android.package-archive")
        view.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        context.startActivity(view)
    }
}
