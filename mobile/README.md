# UBETRA Android APK (Capacitor)

Native shell that loads **https://ubeneeko.duckdns.org** inside a WebView, with **Firebase Cloud Messaging** for reliable background push. Call ringing / DND bypass is prepared via a dedicated `ubetra_calls` notification channel.

PWAs (Chrome/Edge) cannot reliably ignore Do Not Disturb or show full-screen incoming-call UI. This APK is the path for that.

## Prerequisites

On a machine with **Android Studio** (Java + Android SDK):

1. Node 20+
2. Android Studio Ladybug+ (SDK 35 recommended)
3. A free [Firebase](https://console.firebase.google.com/) project with **Cloud Messaging** enabled
4. This repo checked out

## One-time Firebase setup

1. Create Firebase Android app with package id: `org.duckdns.ubeneeko.app`
2. Download `google-services.json` → place at `mobile/android/app/google-services.json` (after `cap add android`)
3. Project settings → Service accounts → Generate new private key → save as e.g. `~/secrets/ubetra-fcm.json`
4. On Docker-SVR `.env` (never commit):

```env
UBETRA_FCM_SERVICE_ACCOUNT_FILE=/app/backend/data/fcm-service-account.json
UBETRA_FCM_PROJECT_ID=your-firebase-project-id
```

Copy the JSON into the container data volume (same place as `ubetra.db` / `vapid.json`).

## Build the project

```powershell
cd mobile
npm install
npx cap add android          # first time only
npx cap sync android
```

Then:

1. Copy `android-templates/MainActivity.kt` over  
   `android/app/src/main/java/.../MainActivity.java` (convert package path; Capacitor 7 often uses Java — replace with the Kotlin file or port the channel code into Java).
2. Merge permissions from `android-templates/AndroidManifest.permissions.xml` into `android/app/src/main/AndroidManifest.xml`.
3. Ensure the Google Services plugin is applied (Capacitor Push Notifications docs).
4. Put `google-services.json` in `android/app/`.
5. Open Android Studio:

```powershell
npx cap open android
```

6. Build → Build Bundle(s) / APK(s) → APK. Install on phones via USB or internal share.

## App behavior

- Web UI is the same HTTPS site (no separate frontend fork).
- `frontend/app.js` detects Capacitor and registers FCM via `POST /api/push/native` instead of Web Push.
- Server sends native tokens with FCM HTTP v1 **HIGH** priority on channel `ubetra_chat` (or `ubetra_calls` when `kind=call`).
- **Calls / DND:** after install, open Android Settings → Apps → UBETRA → **Do Not Disturb access** (Notification policy) → Allow. The `ubetra_calls` channel is created with `setBypassDnd(true)`.

## Change server URL

Edit `capacitor.config.json` → `server.url`, then `npx cap sync android`.

## PWA vs APK

| | Chrome/Edge PWA | This APK |
|--|--|--|
| Install | Install app from browser | Sideload / Play internal |
| Background chat push | Best-effort (OEM battery) | Native FCM, much better |
| Bypass DND for calls | No | Yes (with policy access) |
| Full-screen incoming call | No | Planned on `ubetra_calls` |

Keep the PWA for desktop; use the APK on Android phones once Firebase is wired.
