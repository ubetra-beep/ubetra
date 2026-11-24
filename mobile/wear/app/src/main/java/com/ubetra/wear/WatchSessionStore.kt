package com.ubetra.wear

import android.content.Context
import android.content.SharedPreferences
import android.util.Base64
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKeys

/**
 * The watch stores the pairing key and the last summary. It does not store
 * a server URL or an account token.
 */
class WatchSessionStore(context: Context) {
    private val prefs: SharedPreferences = open(context.applicationContext)

    fun isPaired(): Boolean = key() != null

    fun key(): ByteArray? {
        val raw = prefs.getString(KEY_KEY, null) ?: return null
        if (raw.isBlank()) return null
        return try {
            Base64.decode(raw, Base64.NO_WRAP)
        } catch (_: Exception) {
            null
        }
    }

    fun saveKey(key: ByteArray) {
        prefs.edit().putString(KEY_KEY, Base64.encodeToString(key, Base64.NO_WRAP)).commit()
    }

    fun writeSummary(json: String) {
        prefs.edit()
            .putString(KEY_SUMMARY, json)
            .putLong(KEY_SUMMARY_AT, System.currentTimeMillis())
            .commit()
    }

    fun readSummary(): Pair<String, Long>? {
        val json = prefs.getString(KEY_SUMMARY, null) ?: return null
        if (json.isBlank()) return null
        return json to prefs.getLong(KEY_SUMMARY_AT, 0L)
    }

    fun clearSummary() {
        prefs.edit().remove(KEY_SUMMARY).remove(KEY_SUMMARY_AT).commit()
    }

    fun clear() {
        prefs.edit().clear().commit()
    }

    private fun open(context: Context): SharedPreferences {
        val masterKeyAlias = MasterKeys.getOrCreate(MasterKeys.AES256_GCM_SPEC)
        return EncryptedSharedPreferences.create(
            "ubetra_wear_session",
            masterKeyAlias,
            context,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }

    private companion object {
        const val KEY_KEY = "aes_key"
        const val KEY_SUMMARY = "summary_json"
        const val KEY_SUMMARY_AT = "summary_at_ms"
    }
}
