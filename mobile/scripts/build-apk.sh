#!/usr/bin/env bash
# Build UBETRA Android debug APK on Docker-SVR (Node + Android SDK containers).
# Also builds the Wear OS module when the SDK image can compile it.
# Usage (on Docker-SVR):
#   bash mobile/scripts/build-apk.sh
#   bash mobile/scripts/build-apk.sh --wear-only
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

WEAR_ONLY=0
if [[ "${1:-}" == "--wear-only" ]]; then
  WEAR_ONLY=1
elif [[ $# -gt 0 ]]; then
  echo "Usage: bash mobile/scripts/build-apk.sh [--wear-only]" >&2
  exit 1
fi

mkdir -p "$DIST"

ensure_signing() {
  mkdir -p "$MOBILE/keystore"
  local ks="$MOBILE/keystore/ubetra.jks"
  local pass_file="$MOBILE/keystore/password"
  if [[ ! -f "$pass_file" ]]; then
    python3 -c "import secrets; print(secrets.token_urlsafe(24), end='')" > "$pass_file"
  fi
  UBETRA_KEYSTORE_PASSWORD="$(cat "$pass_file")"
  if [[ ! -f "$ks" ]]; then
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
}

build_wear_apk() {
  mkdir -p "$DIST"
  local log="$DIST/ubetra-wear-build.log"
  local gradle_home="${UBETRA_WEAR_GRADLE_HOME:-$HOME/.cache/ubetra-wear-gradle}"
  mkdir -p "$gradle_home"
  echo "==> Wear: chown module for Android SDK user ${SDK_UID}:${SDK_GID}"
  docker run --rm -v "$MOBILE:/app" -v "$gradle_home:/gradle-home" alpine \
    chown -R "${SDK_UID}:${SDK_GID}" /app/wear /gradle-home
  echo "==> Wear: Gradle assembleDebug and bundleRelease (com.ubetra.wear)"
  set +e
  docker run --rm \
    -v "$MOBILE:/app" \
    -v "$gradle_home:/tmp/gradle-home" \
    -w /app/wear \
    -e GRADLE_USER_HOME=/tmp/gradle-home \
    -e UBETRA_KEYSTORE_PASSWORD="$UBETRA_KEYSTORE_PASSWORD" \
    "$IMAGE_SDK" \
    bash -lc 'mkdir -p /tmp/gradle-home; yes | sdkmanager --sdk_root="$ANDROID_HOME" --licenses >/tmp/sdk-licenses.log || true; sdkmanager --sdk_root="$ANDROID_HOME" --install "platforms;android-35" "build-tools;35.0.0"; chmod +x ./gradlew; ./gradlew :app:assembleDebug :app:bundleRelease --no-daemon' \
    2>&1 | tee "$log"
  status=${PIPESTATUS[0]}
  docker run --rm -v "$MOBILE:/app" alpine chown -R "${HOST_UID}:${HOST_GID}" /app/wear || true
  set -e
  if [[ "$status" -ne 0 ]]; then
    echo "ERROR: Wear APK build failed (exit $status). See $log" >&2
    python3 - "$DIST/ubetra-wear.json" "$status" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
path, code = sys.argv[1], sys.argv[2]
Path(path).write_text(json.dumps({
    "built": False,
    "filename": "ubetra-wear.apk",
    "application_id": "com.ubetra.wear",
    "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "error": f"Wear Gradle failed (exit {code}). See mobile/dist/ubetra-wear-build.log",
}, indent=2) + "\n")
PY
    return "$status"
  fi
  local apk
  apk="$(find "$MOBILE/wear/app/build/outputs/apk" -name 'app-debug.apk' | head -1 || true)"
  if [[ -z "$apk" ]]; then
    apk="$(find "$MOBILE/wear/app/build/outputs/apk" -name '*.apk' | head -1 || true)"
  fi
  if [[ -z "$apk" ]]; then
    echo "ERROR: Wear APK not found" >&2
    return 1
  fi
  cp -f "$apk" "$DIST/ubetra-wear.apk"
  local aab
  aab="$(find "$MOBILE/wear/app/build/outputs/bundle" -name '*.aab' | head -1 || true)"
  if [[ -n "$aab" ]]; then
    cp -f "$aab" "$DIST/ubetra-wear.aab"
    ls -lh "$DIST/ubetra-wear.aab"
  else
    echo "WARNING: Wear AAB was not produced. See $log" >&2
  fi
  python3 - "$DIST/ubetra-wear.json" "$MOBILE/apk-version.json" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
dest, version_file = sys.argv[1], sys.argv[2]
meta = {"version": "", "version_code": 0}
path = Path(version_file)
if path.is_file():
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(loaded, dict):
        meta = loaded
Path(dest).write_text(json.dumps({
    "built": True,
    "version": str(meta.get("version") or ""),
    "version_code": int(meta.get("version_code") or 0),
    "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "filename": "ubetra-wear.apk",
    "aab": "ubetra-wear.aab",
    "application_id": "com.ubetra.wear",
}, indent=2) + "\n")
PY
  ls -lh "$DIST/ubetra-wear.apk"
  echo "==> Wear done: $DIST/ubetra-wear.apk"
  return 0
}

if [[ "$WEAR_ONLY" == "1" ]]; then
  ensure_signing
  build_wear_apk
  exit $?
fi

sync_bundled_www() {
  echo "==> Bundle phone-only shell from frontend/"
  mkdir -p "$MOBILE/www/assets"
  cp -f "$ROOT/frontend/index.html" "$MOBILE/www/shell.html"
  cp -f "$ROOT/frontend/"*.js "$ROOT/frontend/"*.css "$MOBILE/www/assets/"
  if [[ -f "$ROOT/frontend/sw.js" ]]; then
    cp -f "$ROOT/frontend/sw.js" "$MOBILE/www/sw.js"
  fi
}

NODE_RUN=(docker run --rm -u "${HOST_UID}:${HOST_GID}" -e HOME=/tmp -v "$MOBILE:/app" -w /app "$IMAGE_NODE")

sync_bundled_www

echo "==> Sync npm deps"
"${NODE_RUN[@]}" bash -lc 'npm ci || npm install'

APP_GRADLE_CHECK="$MOBILE/android/app/build.gradle"
if [[ -d "$MOBILE/android" && -f "$APP_GRADLE_CHECK" ]] && ! grep -q 'com.ubetra.app' "$APP_GRADLE_CHECK"; then
  echo "==> Application id changed; recreating the Capacitor android project"
  rm -rf "$MOBILE/android"
fi

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
package com.ubetra.app;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Context;
import android.content.Intent;
import android.media.AudioAttributes;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.provider.Settings;
import android.widget.Toast;
import androidx.core.content.FileProvider;
import androidx.webkit.WebViewCompat;
import androidx.webkit.WebViewFeature;
import com.getcapacitor.BridgeActivity;
import java.io.File;
import java.util.Collections;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import com.ubetra.appupdater.UbetraAppUpdaterPlugin;
import com.ubetra.healthconnect.UbetraHealthConnectPlugin;
import com.ubetra.localstore.UbetraLocalStorePlugin;

public class MainActivity extends BridgeActivity {
  @Override
  public void onCreate(Bundle savedInstanceState) {
    registerPlugin(UbetraHealthConnectPlugin.class);
    registerPlugin(UbetraMediaPlugin.class);
    registerPlugin(UbetraLocalStorePlugin.class);
    registerPlugin(UbetraAppUpdaterPlugin.class);
    super.onCreate(savedInstanceState);
    createChannels();
    attachDownloadListener();
    allowSelfHostNavigation();
    injectNativeBridgeForServerPages();
  }

  @Override
  public void onResume() {
    super.onResume();
    attachDownloadListener();
    allowSelfHostNavigation();
  }

  private boolean nativeBridgeInjected = false;

  private void injectNativeBridgeForServerPages() {
    if (nativeBridgeInjected || getBridge() == null || getBridge().getWebView() == null) return;
    if (!WebViewFeature.isFeatureSupported(WebViewFeature.DOCUMENT_START_SCRIPT)) return;
    try {
      java.lang.reflect.Method injectorMethod = getBridge().getClass().getDeclaredMethod("getJSInjector");
      injectorMethod.setAccessible(true);
      Object injector = injectorMethod.invoke(getBridge());
      if (injector == null) return;
      String script = (String) injector.getClass().getMethod("getScriptString").invoke(injector);
      WebViewCompat.addDocumentStartJavaScript(
        getBridge().getWebView(),
        script,
        Collections.singleton("*")
      );
      nativeBridgeInjected = true;
    } catch (Exception ignored) {
    }
  }

  private void allowSelfHostNavigation() {
    if (getBridge() == null || getBridge().getWebView() == null) return;
    getBridge().getWebView().setWebViewClient(new com.getcapacitor.BridgeWebViewClient(getBridge()) {
      @Override
      public boolean shouldOverrideUrlLoading(android.webkit.WebView view, android.webkit.WebResourceRequest request) {
        String scheme = request.getUrl().getScheme();
        if ("https".equalsIgnoreCase(scheme) || "http".equalsIgnoreCase(scheme)) return false;
        return super.shouldOverrideUrlLoading(view, request);
      }
    });
  }

  private void attachDownloadListener() {
    if (getBridge() == null || getBridge().getWebView() == null) return;
    getBridge().getWebView().setDownloadListener((url, userAgent, contentDisposition, mimeType, contentLength) -> {
      Toast.makeText(this, "Downloading update…", Toast.LENGTH_SHORT).show();
      new Thread(() -> {
        File tmp = null;
        HttpURLConnection conn = null;
        try {
          File dir = getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS);
          if (dir == null) throw new IllegalStateException("No download directory");
          if (!dir.exists() && !dir.mkdirs()) throw new IllegalStateException("No download directory");
          tmp = new File(dir, "ubetra.apk.part");
          if (tmp.exists()) tmp.delete();
          File apk = new File(dir, "ubetra.apk");
          conn = (HttpURLConnection) new URL(url).openConnection();
          conn.setInstanceFollowRedirects(true);
          conn.setConnectTimeout(20000);
          conn.setReadTimeout(120000);
          conn.setRequestProperty("Accept-Encoding", "identity");
          int code = conn.getResponseCode();
          if (code != HttpURLConnection.HTTP_OK) throw new IllegalStateException("Download failed (" + code + ")");
          try (InputStream in = conn.getInputStream(); FileOutputStream out = new FileOutputStream(tmp)) {
            byte[] buf = new byte[65536];
            int n;
            while ((n = in.read(buf)) >= 0) out.write(buf, 0, n);
          }
          if (tmp.length() < 100000L) throw new IllegalStateException("Download failed");
          if (apk.exists()) apk.delete();
          if (!tmp.renameTo(apk)) throw new IllegalStateException("Could not save the APK");
          tmp = null;
          runOnUiThread(() -> openDownloadedApk(apk));
        } catch (Exception err) {
          if (tmp != null) tmp.delete();
          runOnUiThread(() -> Toast.makeText(this, "Could not start download: " + err.getMessage(), Toast.LENGTH_LONG).show());
        } finally {
          if (conn != null) conn.disconnect();
        }
      }).start();
    });
  }

  private void openDownloadedApk(File apk) {
    try {
      Uri uri = FileProvider.getUriForFile(this, getPackageName() + ".fileprovider", apk);
      Intent view = new Intent(Intent.ACTION_VIEW);
      view.setDataAndType(uri, "application/vnd.android.package-archive");
      view.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
      startActivity(view);
    } catch (Exception err) {
      Toast.makeText(this, "Could not open installer: " + err.getMessage(), Toast.LENGTH_LONG).show();
    }
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

    NotificationChannel tasks = new NotificationChannel(
      "ubetra_tasks",
      "Tasks",
      NotificationManager.IMPORTANCE_HIGH
    );
    tasks.setDescription("Task added, due soon, and reminder alerts");
    tasks.enableVibration(true);
    tasks.setShowBadge(true);
    tasks.setSound(Settings.System.DEFAULT_NOTIFICATION_URI, attrs);
    manager.createNotificationChannel(tasks);
  }
}
JAVA
fi

if [[ -n "$JAVA_MAIN" ]]; then
  JAVA_DIR="$(dirname "$JAVA_MAIN")"
  cp "$MOBILE/android-templates/UbetraMediaPlugin.java" "$JAVA_DIR/UbetraMediaPlugin.java"
  echo "==> Installed UbetraMediaPlugin"
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
    'android.permission.CAMERA' \
    'android.permission.RECORD_AUDIO' \
    'android.permission.MODIFY_AUDIO_SETTINGS' \
    'android.permission.FLASHLIGHT' \
    'android.permission.FOREGROUND_SERVICE' \
    'android.permission.FOREGROUND_SERVICE_SPECIAL_USE' \
    'android.permission.RECEIVE_BOOT_COMPLETED' \
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
          "package_name": "com.ubetra.app"
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
if [[ -f "$APP_GRADLE" ]] && ! grep -q 'androidx.webkit:webkit' "$APP_GRADLE"; then
  sed -i "/implementation project(':capacitor-android')/a\\    implementation \"androidx.webkit:webkit:1.12.1\"" "$APP_GRADLE"
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

FILE_PATHS="$(find "$MOBILE/android" -name 'file_paths.xml' | head -1 || true)"
if [[ -n "$FILE_PATHS" ]]; then
  python3 - "$FILE_PATHS" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
text = path.read_text()
if 'path="Download/"' not in text:
    text = text.replace("</paths>", '    <external-files-path name="apk" path="Download/" />\n</paths>')
    path.write_text(text)
    print("patched", path)
PY
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

ensure_signing
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

echo "==> Gradle assembleDebug bundleRelease"
set +e
docker run --rm \
  -v "$MOBILE:/app" \
  -w /app/android \
  -e GRADLE_USER_HOME=/tmp/gradle-home \
  -e UBETRA_KEYSTORE_PASSWORD="$UBETRA_KEYSTORE_PASSWORD" \
  "$IMAGE_SDK" \
  bash -lc 'mkdir -p /tmp/gradle-home; ./gradlew assembleDebug bundleRelease --no-daemon' \
  2>&1 | tee /tmp/ubetra-phone-build.log
phone_status=${PIPESTATUS[0]}
set -e
cp -f /tmp/ubetra-phone-build.log "$DIST/ubetra-build.log" 2>/dev/null || true
if [[ "$phone_status" -ne 0 ]]; then
  echo "ERROR: Phone Gradle failed (exit $phone_status). See $DIST/ubetra-build.log" >&2
  python3 - "$DIST/ubetra.json" "$phone_status" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
path, code = sys.argv[1], sys.argv[2]
Path(path).write_text(json.dumps({
    "built": False,
    "filename": "ubetra.aab",
    "application_id": "com.ubetra.app",
    "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "error": f"Phone Gradle failed (exit {code}). See mobile/dist/ubetra-build.log",
}, indent=2) + "\n")
PY
  docker run --rm -v "$MOBILE:/app" alpine chown -R "${HOST_UID}:${HOST_GID}" /app || true
  exit "$phone_status"
fi

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
AAB="$(find "$MOBILE/android/app/build/outputs/bundle" -name '*.aab' | head -1 || true)"
AAB_NAME=""
if [[ -n "$AAB" ]]; then
  cp -f "$AAB" "$DIST/ubetra.aab"
  AAB_NAME="ubetra.aab"
  ls -lh "$DIST/ubetra.aab"
else
  echo "WARNING: Phone AAB was not produced. See $DIST/ubetra-build.log" >&2
fi
python3 - <<PY
import json
from datetime import datetime, timezone
from pathlib import Path
meta = {
    "built": True,
    "version": "${VERSION_NAME}",
    "version_code": int("${VERSION_CODE}"),
    "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "filename": "ubetra.apk",
    "aab": "${AAB_NAME}",
    "application_id": "com.ubetra.app",
}
Path("${DIST}/ubetra.json").write_text(json.dumps(meta, indent=2) + "\n")
PY
ls -lh "$DIST/ubetra.apk"
echo "==> Done: $DIST/ubetra.apk ($VERSION_NAME / $VERSION_CODE)"

set +e
build_wear_apk
wear_status=$?
set -e
if [[ "$wear_status" -ne 0 ]]; then
  echo "WARNING: Wear APK was not built (exit $wear_status). Phone APK is still $DIST/ubetra.apk" >&2
fi
