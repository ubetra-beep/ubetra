#!/usr/bin/env bash
# Build UBETRA Android debug APK on Docker-SVR (Node + Android SDK containers).
# Usage (on Docker-SVR): bash mobile/scripts/build-apk.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
MOBILE="$ROOT/mobile"
DIST="$MOBILE/dist"
IMAGE_NODE="${UBETRA_NODE_IMAGE:-node:22-bookworm}"
IMAGE_SDK="${UBETRA_ANDROID_SDK_IMAGE:-mobiledevops/android-sdk-image:34.0.0}"
HOST_UID="$(id -u)"
HOST_GID="$(id -g)"
SDK_UID=999
SDK_GID=996

mkdir -p "$DIST"

NODE_RUN=(docker run --rm -u "${HOST_UID}:${HOST_GID}" -e HOME=/tmp -v "$MOBILE:/app" -w /app "$IMAGE_NODE")

echo "==> Sync npm deps"
"${NODE_RUN[@]}" bash -lc 'npm ci || npm install'

if [[ ! -d "$MOBILE/android" ]]; then
  echo "==> Adding Capacitor Android platform"
  "${NODE_RUN[@]}" bash -lc 'npx cap add android'
else
  echo "==> Sync Capacitor Android"
  "${NODE_RUN[@]}" bash -lc 'npx cap sync android'
fi

JAVA_MAIN="$(find "$MOBILE/android/app/src/main/java" -name 'MainActivity.java' 2>/dev/null | head -1 || true)"
if [[ -n "$JAVA_MAIN" ]]; then
  echo "==> Patch MainActivity (notification channels + APK downloads)"
  cat > "$JAVA_MAIN" <<'JAVA'
package org.duckdns.ubeneeko.app;

import android.app.DownloadManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Context;
import android.media.AudioAttributes;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.provider.Settings;
import android.webkit.CookieManager;
import android.webkit.URLUtil;
import android.widget.Toast;
import com.getcapacitor.BridgeActivity;
import org.duckdns.ubeneeko.healthconnect.UbetraHealthConnectPlugin;

public class MainActivity extends BridgeActivity {
  @Override
  public void onCreate(Bundle savedInstanceState) {
    registerPlugin(UbetraHealthConnectPlugin.class);
    super.onCreate(savedInstanceState);
    createChannels();
    attachDownloadListener();
  }

  @Override
  public void onResume() {
    super.onResume();
    attachDownloadListener();
  }

  private void attachDownloadListener() {
    if (getBridge() == null || getBridge().getWebView() == null) return;
    getBridge().getWebView().setDownloadListener((url, userAgent, contentDisposition, mimeType, contentLength) -> {
      try {
        DownloadManager.Request request = new DownloadManager.Request(Uri.parse(url));
        String mime = (mimeType == null || mimeType.isEmpty())
          ? "application/vnd.android.package-archive"
          : mimeType;
        request.setMimeType(mime);
        String cookies = CookieManager.getInstance().getCookie(url);
        if (cookies != null) request.addRequestHeader("cookie", cookies);
        request.addRequestHeader("User-Agent", userAgent);
        request.setDescription("UBETRA update");
        String name = URLUtil.guessFileName(url, contentDisposition, mime);
        if (name == null || !name.toLowerCase().endsWith(".apk")) name = "ubetra.apk";
        request.setTitle(name);
        request.allowScanningByMediaScanner();
        request.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
        request.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, name);
        DownloadManager manager = (DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE);
        if (manager == null) throw new IllegalStateException("No download manager");
        manager.enqueue(request);
        Toast.makeText(
          this,
          "Downloading update. When it finishes, close UBETRA completely, then tap the download to install.",
          Toast.LENGTH_LONG
        ).show();
      } catch (Exception err) {
        Toast.makeText(this, "Could not start download: " + err.getMessage(), Toast.LENGTH_LONG).show();
      }
    });
  }

  private void createChannels() {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return;
    NotificationManager manager = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
    if (manager == null) return;

    NotificationChannel chat = new NotificationChannel(
      "ubetra_chat",
      "Chat",
      NotificationManager.IMPORTANCE_HIGH
    );
    chat.setDescription("Partner chat and activity alerts");
    chat.enableVibration(true);
    chat.setShowBadge(true);

    AudioAttributes attrs = new AudioAttributes.Builder()
      .setUsage(AudioAttributes.USAGE_NOTIFICATION_RINGTONE)
      .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
      .build();

    NotificationChannel calls = new NotificationChannel(
      "ubetra_calls",
      "Calls",
      NotificationManager.IMPORTANCE_HIGH
    );
    calls.setDescription("Incoming calls — can bypass Do Not Disturb after you grant access");
    calls.enableVibration(true);
    Uri ringtone = Settings.System.DEFAULT_RINGTONE_URI;
    calls.setSound(ringtone, attrs);
    calls.setBypassDnd(true);
    calls.setLockscreenVisibility(Notification.VISIBILITY_PUBLIC);

    manager.createNotificationChannel(chat);
    manager.createNotificationChannel(calls);
  }
}
JAVA
fi

MANIFEST="$MOBILE/android/app/src/main/AndroidManifest.xml"
if [[ -f "$MANIFEST" ]]; then
  for perm in \
    'android.permission.POST_NOTIFICATIONS' \
    'android.permission.VIBRATE' \
    'android.permission.WAKE_LOCK' \
    'android.permission.USE_FULL_SCREEN_INTENT' \
    'android.permission.ACCESS_NOTIFICATION_POLICY' \
    'android.permission.REQUEST_INSTALL_PACKAGES' \
    'android.permission.WRITE_EXTERNAL_STORAGE' \
    'android.permission.health.READ_SLEEP' \
    'android.permission.health.READ_MENSTRUATION' \
    'android.permission.health.READ_HEALTH_DATA_HISTORY'
  do
    if ! grep -q "$perm" "$MANIFEST"; then
      sed -i "s|<application|    <uses-permission android:name=\"$perm\" />\\n    <application|" "$MANIFEST"
    fi
  done
  python3 - "$MANIFEST" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
if "com.google.android.apps.healthdata" not in text:
    needle = "<manifest"
    idx = text.find(needle)
    if idx >= 0:
        end = text.find(">", idx)
        text = text[: end + 1] + '\n    <queries>\n        <package android:name="com.google.android.apps.healthdata" />\n    </queries>' + text[end + 1 :]
rationale = """        <intent-filter>
            <action android:name="androidx.health.ACTION_SHOW_PERMISSIONS_RATIONALE" />
        </intent-filter>
        <intent-filter>
            <action android:name="android.intent.action.VIEW_PERMISSION_USAGE" />
            <category android:name="android.intent.category.HEALTH_PERMISSIONS" />
        </intent-filter>
"""
if "ACTION_SHOW_PERMISSIONS_RATIONALE" not in text:
    text = text.replace("</activity>", rationale + "    </activity>", 1)
path.write_text(text, encoding="utf-8")
print("==> Health Connect manifest filters")
PY
fi

GS="$MOBILE/android/app/google-services.json"
if [[ ! -f "$GS" ]]; then
  if [[ -f "$MOBILE/google-services.json" ]]; then
    cp "$MOBILE/google-services.json" "$GS"
  else
    echo "==> Placeholder google-services.json (replace with real Firebase for native FCM)"
    cat > "$GS" <<'JSON'
{
  "project_info": {
    "project_number": "000000000000",
    "project_id": "ubetra-placeholder",
    "storage_bucket": "ubetra-placeholder.appspot.com"
  },
  "client": [
    {
      "client_info": {
        "mobilesdk_app_id": "1:000000000000:android:0000000000000000000000",
        "android_client_info": {
          "package_name": "org.duckdns.ubeneeko.app"
        }
      },
      "oauth_client": [],
      "api_key": [{ "current_key": "AIzaSyPlaceholderReplaceWithFirebaseKey000000" }],
      "services": { "appinvite_service": { "other_platform_oauth_client": [] } }
    }
  ],
  "configuration_version": "1"
}
JSON
  fi
fi

ROOT_GRADLE="$MOBILE/android/build.gradle"
APP_GRADLE="$MOBILE/android/app/build.gradle"
if [[ -f "$ROOT_GRADLE" ]] && ! grep -q 'google-services' "$ROOT_GRADLE"; then
  sed -i "/dependencies {/a\\        classpath 'com.google.gms:google-services:4.4.2'" "$ROOT_GRADLE" || true
fi
if [[ -f "$ROOT_GRADLE" ]] && ! grep -q 'kotlin-gradle-plugin' "$ROOT_GRADLE"; then
  sed -i "/dependencies {/a\\        classpath 'org.jetbrains.kotlin:kotlin-gradle-plugin:1.9.25'" "$ROOT_GRADLE" || true
fi
if [[ -f "$APP_GRADLE" ]] && ! grep -q "com.google.gms.google-services" "$APP_GRADLE"; then
  echo "apply plugin: 'com.google.gms.google-services'" >> "$APP_GRADLE"
fi

VERSION_FILE="$MOBILE/apk-version.json"
VERSION_NAME="0.81.0"
VERSION_CODE="81"
if [[ -f "$VERSION_FILE" ]]; then
  VERSION_NAME="$(python3 -c "import json; print(json.load(open('$VERSION_FILE'))['version'])")"
  VERSION_CODE="$(python3 -c "import json; print(json.load(open('$VERSION_FILE'))['version_code'])")"
fi
if [[ -f "$APP_GRADLE" ]]; then
  echo "==> Set versionName $VERSION_NAME versionCode $VERSION_CODE"
  sed -i "s/versionCode [0-9][0-9]*/versionCode ${VERSION_CODE}/" "$APP_GRADLE"
  sed -i "s/versionName \".*\"/versionName \"${VERSION_NAME}\"/" "$APP_GRADLE"
fi

VARS="$MOBILE/android/variables.gradle"
if [[ -f "$VARS" ]]; then
  echo "==> Health Connect needs minSdk 26"
  sed -i 's/minSdkVersion = 22/minSdkVersion = 26/' "$VARS"
  sed -i 's/minSdkVersion = 23/minSdkVersion = 26/' "$VARS"
fi

if [[ -d "$MOBILE/android-icons" && -d "$MOBILE/android/app/src/main/res" ]]; then
  echo "==> Install bird launcher icons (violet adaptive background)"
  cp -a "$MOBILE/android-icons/." "$MOBILE/android/app/src/main/res/"
fi

mkdir -p "$MOBILE/keystore"
KS="$MOBILE/keystore/ubetra.jks"
PASS_FILE="$MOBILE/keystore/password"
if [[ ! -f "$PASS_FILE" ]]; then
  python3 -c "import secrets; print(secrets.token_urlsafe(24), end='')" > "$PASS_FILE"
fi
UBETRA_KEYSTORE_PASSWORD="$(cat "$PASS_FILE")"
if [[ ! -f "$KS" ]]; then
  echo "==> Creating persistent signing keystore (kept on this server)"
  docker run --rm -u "${HOST_UID}:${HOST_GID}" -v "$MOBILE:/app" "$IMAGE_SDK" \
    keytool -genkeypair \
      -keystore /app/keystore/ubetra.jks \
      -alias ubetra \
      -keyalg RSA -keysize 2048 -validity 10000 \
      -storepass "$UBETRA_KEYSTORE_PASSWORD" \
      -keypass "$UBETRA_KEYSTORE_PASSWORD" \
      -dname "CN=UBETRA, OU=UBETRA, O=UBETRA, L=Home, ST=NA, C=US"
fi
if [[ -f "$APP_GRADLE" ]] && ! grep -q "UBETRA_SIGNING" "$APP_GRADLE"; then
  echo "==> Wire Gradle to the persistent keystore"
  cat >> "$APP_GRADLE" <<'GRADLE'

// UBETRA_SIGNING
def ubetraKs = file("${rootProject.projectDir}/../keystore/ubetra.jks")
if (ubetraKs.exists()) {
    android.signingConfigs.create("ubetra") {
        storeFile ubetraKs
        storePassword System.getenv("UBETRA_KEYSTORE_PASSWORD")
        keyAlias "ubetra"
        keyPassword System.getenv("UBETRA_KEYSTORE_PASSWORD")
    }
    android.buildTypes.debug.signingConfig android.signingConfigs.ubetra
    android.buildTypes.release.signingConfig android.signingConfigs.ubetra
}
GRADLE
fi

echo "==> chown for Android SDK container user ${SDK_UID}:${SDK_GID}"
docker run --rm -v "$MOBILE:/app" alpine chown -R "${SDK_UID}:${SDK_GID}" /app

echo "==> Gradle assembleDebug"
docker run --rm \
  -v "$MOBILE:/app" \
  -w /app/android \
  -e GRADLE_USER_HOME=/tmp/gradle-home \
  -e UBETRA_KEYSTORE_PASSWORD="$UBETRA_KEYSTORE_PASSWORD" \
  "$IMAGE_SDK" \
  bash -lc 'mkdir -p /tmp/gradle-home; ./gradlew assembleDebug --no-daemon'

echo "==> Restore ownership to ${HOST_UID}:${HOST_GID}"
docker run --rm -v "$MOBILE:/app" alpine chown -R "${HOST_UID}:${HOST_GID}" /app

APK="$(find "$MOBILE/android/app/build/outputs/apk" -name 'app-debug.apk' | head -1 || true)"
if [[ -z "$APK" ]]; then
  APK="$(find "$MOBILE/android/app/build/outputs/apk" -name '*.apk' | head -1 || true)"
fi
if [[ -z "$APK" ]]; then
  echo "ERROR: APK not found" >&2
  exit 1
fi
cp -f "$APK" "$DIST/ubetra-debug.apk"
cp -f "$APK" "$DIST/ubetra.apk"
python3 - <<PY
import json
from datetime import datetime, timezone
from pathlib import Path
meta = {
    "version": "${VERSION_NAME}",
    "version_code": int("${VERSION_CODE}"),
    "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "filename": "ubetra.apk",
}
Path("${DIST}/ubetra.json").write_text(json.dumps(meta, indent=2) + "\n")
PY
ls -lh "$DIST/ubetra.apk"
echo "==> Done: $DIST/ubetra.apk ($VERSION_NAME / $VERSION_CODE)"
