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
  echo "==> Patch MainActivity notification channels"
  cat > "$JAVA_MAIN" <<'JAVA'
package org.duckdns.ubeneeko.app;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Context;
import android.media.AudioAttributes;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
  @Override
  public void onCreate(Bundle savedInstanceState) {
    super.onCreate(savedInstanceState);
    createChannels();
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
    'android.permission.ACCESS_NOTIFICATION_POLICY'
  do
    if ! grep -q "$perm" "$MANIFEST"; then
      sed -i "s|<application|    <uses-permission android:name=\"$perm\" />\\n    <application|" "$MANIFEST"
    fi
  done
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
if [[ -f "$APP_GRADLE" ]] && ! grep -q "com.google.gms.google-services" "$APP_GRADLE"; then
  echo "apply plugin: 'com.google.gms.google-services'" >> "$APP_GRADLE"
fi

echo "==> chown for Android SDK container user ${SDK_UID}:${SDK_GID}"
docker run --rm -v "$MOBILE:/app" alpine chown -R "${SDK_UID}:${SDK_GID}" /app

echo "==> Gradle assembleDebug"
docker run --rm \
  -v "$MOBILE:/app" \
  -w /app/android \
  -e GRADLE_USER_HOME=/tmp/gradle-home \
  "$IMAGE_SDK" \
  bash -lc 'mkdir -p /tmp/gradle-home; ./gradlew assembleDebug --no-daemon'

echo "==> Restore ownership to ${HOST_UID}:${HOST_GID}"
docker run --rm -v "$MOBILE:/app" alpine chown -R "${HOST_UID}:${HOST_GID}" /app

APK="$(find "$MOBILE/android/app/build/outputs/apk" -name '*.apk' | head -1 || true)"
if [[ -z "$APK" ]]; then
  echo "ERROR: APK not found" >&2
  exit 1
fi
cp -f "$APK" "$DIST/ubetra-debug.apk"
ls -lh "$DIST/ubetra-debug.apk"
echo "==> Done: $DIST/ubetra-debug.apk"
