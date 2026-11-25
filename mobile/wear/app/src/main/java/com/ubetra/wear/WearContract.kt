package com.ubetra.wear

const val FINISH_ON_PHONE = "Finish on phone"
const val OPEN_PHONE = "Open phone"
const val FINISH_ON_PHONE_CONFLICT = "Finish on phone."

const val EXTRA_BANNER = "com.ubetra.wear.FINISH_ON_PHONE"

const val PATH_REQ = "/ubetra/req"
const val PATH_RES = "/ubetra/res"
const val PATH_SUMMARY = "/ubetra/summary"
const val PHONE_CAPABILITY = "ubetra_phone"

/** Pairing alphabet. I, O, 0, and 1 are omitted. */
const val PAIR_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

val LOCK_ACTION_IDS = setOf(
    "lock",
    "sleep_break",
    "hygiene_break",
    "relock",
    "unlock",
    "extend_1h",
    "extend_4h",
    "confirm_release",
)

val LOG_ACTION_IDS = setOf(
    "log_full",
    "log_ruined",
    "log_denied",
    "log_play",
)

fun normalizePairCode(raw: String): String =
    raw.uppercase().filter { it.isLetterOrDigit() }

fun formatPairCode(raw: String): String {
    val code = normalizePairCode(raw).take(8)
    return if (code.length > 4) code.substring(0, 4) + "-" + code.substring(4) else code
}
