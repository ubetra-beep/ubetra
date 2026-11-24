package com.ubetra.wear

import android.util.Base64
import org.json.JSONObject
import java.security.SecureRandom
import javax.crypto.Cipher
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

/** Same AES-GCM envelope as the phone. Version, nonce, ciphertext. No tokens. */
object WearCrypto {
    const val VERSION = 1

    fun encrypt(key: ByteArray, plain: ByteArray): String {
        val nonce = ByteArray(12)
        SecureRandom().nextBytes(nonce)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(128, nonce))
        val ct = cipher.doFinal(plain)
        return JSONObject()
            .put("v", VERSION)
            .put("nonce", Base64.encodeToString(nonce, Base64.NO_WRAP))
            .put("ct", Base64.encodeToString(ct, Base64.NO_WRAP))
            .toString()
    }

    fun decrypt(key: ByteArray, envelopeJson: String): ByteArray {
        val envelope = JSONObject(envelopeJson)
        if (envelope.optInt("v") != VERSION) throw IllegalArgumentException("Unsupported wear payload")
        val nonce = Base64.decode(envelope.getString("nonce"), Base64.NO_WRAP)
        val ct = Base64.decode(envelope.getString("ct"), Base64.NO_WRAP)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(128, nonce))
        return cipher.doFinal(ct)
    }
}
