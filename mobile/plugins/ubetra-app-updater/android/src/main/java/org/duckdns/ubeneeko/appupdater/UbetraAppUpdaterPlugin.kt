package org.duckdns.ubeneeko.appupdater

import android.content.Intent
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
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL

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
        val tmp = File(dir, "ubetra.apk.part")
        if (tmp.exists()) tmp.delete()
        var conn: HttpURLConnection? = null
        try {
            conn = (URL(url).openConnection() as HttpURLConnection).apply {
                instanceFollowRedirects = true
                connectTimeout = 20000
                readTimeout = 120000
                setRequestProperty("Accept-Encoding", "identity")
                setRequestProperty("User-Agent", "UBETRA-updater")
            }
            val code = conn.responseCode
            if (code != HttpURLConnection.HTTP_OK) {
                call.reject("Download failed ($code)")
                return
            }
            conn.inputStream.use { input ->
                FileOutputStream(tmp).use { output ->
                    val buf = ByteArray(65536)
                    while (true) {
                        val n = input.read(buf)
                        if (n < 0) break
                        output.write(buf, 0, n)
                    }
                }
            }
            if (tmp.length() < 100000L) {
                tmp.delete()
                call.reject("Download failed")
                return
            }
            if (apk.exists()) apk.delete()
            if (!tmp.renameTo(apk)) {
                tmp.copyTo(apk, overwrite = true)
                tmp.delete()
            }
            val host = activity
            if (host != null) host.runOnUiThread { openInstaller(apk) } else openInstaller(apk)
            val ret = JSObject()
            ret.put("installed", true)
            call.resolve(ret)
        } catch (err: Exception) {
            tmp.delete()
            call.reject(err.message ?: "Download failed")
        } finally {
            conn?.disconnect()
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
