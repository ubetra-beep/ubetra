plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

val versionFile = rootProject.file("../apk-version.json")
val versionNameFromFile = Regex(""""version"\s*:\s*"([^"]+)"""")
    .find(if (versionFile.exists()) versionFile.readText() else "")
    ?.groupValues
    ?.get(1)
    ?: "0.91.0"
val versionCodeFromFile = Regex(""""version_code"\s*:\s*(\d+)""")
    .find(if (versionFile.exists()) versionFile.readText() else "")
    ?.groupValues
    ?.get(1)
    ?.toInt()
    ?: 91

// Wear APK. It cannot share the phone applicationId com.ubetra.app.
// Same upload keystore: mobile/keystore/ubetra.jks, alias ubetra.
val keystoreFile = rootProject.file("../keystore/ubetra.jks")
val keystorePassword = System.getenv("UBETRA_KEYSTORE_PASSWORD").orEmpty()

android {
    namespace = "com.ubetra.wear"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.ubetra.wear"
        minSdk = 30
        targetSdk = 35
        versionCode = versionCodeFromFile
        versionName = versionNameFromFile
    }

    signingConfigs {
        create("ubetra") {
            if (keystoreFile.exists()) {
                storeFile = keystoreFile
                storePassword = keystorePassword
                keyAlias = "ubetra"
                keyPassword = keystorePassword
            }
        }
    }

    buildTypes {
        debug {
            if (keystoreFile.exists() && keystorePassword.isNotEmpty()) {
                signingConfig = signingConfigs.getByName("ubetra")
            }
        }
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
            if (keystoreFile.exists() && keystorePassword.isNotEmpty()) {
                signingConfig = signingConfigs.getByName("ubetra")
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        compose = true
    }

    composeOptions {
        kotlinCompilerExtensionVersion = "1.5.15"
    }

    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
            excludes += "META-INF/DEPENDENCIES"
            excludes += "META-INF/INDEX.LIST"
            excludes += "META-INF/LICENSE*"
        }
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.activity:activity-compose:1.9.2")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.6")
    val compose = "1.7.3"
    implementation("androidx.compose.ui:ui:$compose")
    implementation("androidx.compose.foundation:foundation:$compose")
    implementation("androidx.wear.compose:compose-foundation:1.4.0")
    implementation("androidx.wear.compose:compose-material:1.4.0")
    implementation("androidx.wear:wear-input:1.1.0")

    implementation("androidx.wear.tiles:tiles:1.4.1")
    implementation("androidx.wear.protolayout:protolayout:1.2.1")
    implementation("androidx.wear.protolayout:protolayout-material:1.2.1")
    implementation("androidx.wear.protolayout:protolayout-expression:1.2.1")
    implementation("androidx.wear.watchface:watchface-complications-data-source-ktx:1.2.1")

    implementation("androidx.security:security-crypto:1.0.0")
    implementation("androidx.concurrent:concurrent-futures:1.2.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-play-services:1.8.1")
    implementation("com.google.android.gms:play-services-wearable:18.2.0")
}
