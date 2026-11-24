package com.ubetra.wear

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember

class MainActivity : ComponentActivity() {
    private var onBanner: ((String) -> Unit)? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            val banner = remember {
                mutableStateOf(intent.getStringExtra(EXTRA_BANNER)?.let { BannerEvent(it) })
            }
            DisposableEffect(Unit) {
                onBanner = { banner.value = BannerEvent(it) }
                onDispose { onBanner = null }
            }
            WearApp(banner = banner.value?.message, bannerId = banner.value?.id ?: 0L)
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        intent.getStringExtra(EXTRA_BANNER)?.let { message ->
            onBanner?.invoke(message)
        }
    }
}

private data class BannerEvent(
    val message: String,
    val id: Long = System.nanoTime(),
)
