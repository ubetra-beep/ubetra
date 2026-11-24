package com.ubetra.localstore

import android.content.Context
import android.content.SharedPreferences
import android.util.Base64
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKeys

/** Bearer token and the Wear AES key. Neither is written to logcat. */
class SecretStore(context: Context) {
    private val prefs: SharedPreferences = open(context.applicationContext)

    fun token(): String = prefs.getString(KEY_TOKEN, "").orEmpty()

    fun setToken(value: String?) {
        prefs.edit().putString(KEY_TOKEN, value.orEmpty()).commit()
    }

    fun wearKey(): ByteArray? {
        val raw = prefs.getString(KEY_WEAR, null) ?: return null
        if (raw.isBlank()) return null
        return try {
            Base64.decode(raw, Base64.NO_WRAP)
        } catch (_: Exception) {
            null
        }
    }

    fun setWearKey(key: ByteArray?) {
        val editor = prefs.edit()
        if (key == null) editor.remove(KEY_WEAR) else editor.putString(KEY_WEAR, Base64.encodeToString(key, Base64.NO_WRAP))
        editor.commit()
    }

    fun wearNode(): String = prefs.getString(KEY_NODE, "").orEmpty()

    fun setWearNode(nodeId: String?) {
        prefs.edit().putString(KEY_NODE, nodeId.orEmpty()).commit()
    }

    private fun open(context: Context): SharedPreferences {
        val masterKeyAlias = MasterKeys.getOrCreate(MasterKeys.AES256_GCM_SPEC)
        return EncryptedSharedPreferences.create(
            "ubetra_phone_secrets",
            masterKeyAlias,
            context,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }

    private companion object {
        const val KEY_TOKEN = "auth_token"
        const val KEY_WEAR = "wear_key"
        const val KEY_NODE = "wear_node"
    }
}
