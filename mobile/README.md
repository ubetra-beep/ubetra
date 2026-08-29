# UBETRA Android APK (Capacitor)

Native shell that loads your public HTTPS URL (see `capacitor.config.json` → `server.url`) inside a WebView, with **Firebase Cloud Messaging** for reliable background push. Call ringing / DND bypass is prepared via a dedicated `ubetra_calls` notification channel.

PWAs (Chrome/Edge) cannot reliably ignore Do Not Disturb or show full-screen incoming-call UI. This APK is the path for that.

## Prerequisites

On a machine with **Android Studio** (Java + Android SDK):

1. Node 20+
2. Android Studio Ladybug+ (SDK 35 recommended)
3. A free [Firebase](https://console.firebase.google.com/) project with **Cloud Messaging** enabled
4. This repo checked out

## One-time Firebase setup

1. Create a Firebase Android app whose package id matches `appId` in `capacitor.config.json`
2. Download `google-services.json` → place at `mobile/android/app/google-services.json` (after `cap add android`)
3. Project settings → Service accounts → Generate new private key → save as e.g. `~/secrets/ubetra-fcm.json`
4. On the host `.env` (never commit):

```env
UBETRA_FCM_SERVICE_ACCOUNT_FILE=/app/backend/data/fcm-service-account.json
UBETRA_FCM_PROJECT_ID=your-firebase-project-id
```

Copy the JSON into the container data volume (same place as `ubetra.db` / `vapid.json`).

## Build on the host (recommended)

Full Android Studio GUI is not needed — the server uses Docker images:

- `node:22-bookworm` for Capacitor CLI  
- `mobiledevops/android-sdk-image:34.0.0` for Gradle / SDK  

```bash
cd /path/to/ubetra
bash mobile/scripts/build-apk.sh
# → mobile/dist/ubetra.apk  (also copied as ubetra-debug.apk)
```

The web app serves that file at **`/apk/ubetra.apk`** on your public URL. In the Android app, **Settings → This device → Update app** downloads it with the system download manager.

**Installing:** close UBETRA completely, then tap the download. Play Protect may warn (sideload) — tap **Install anyway**.

**“App not installed”:** the previous APKs were signed with a throwaway debug key. Uninstall the old UBETRA **once**, then install 0.82+. Later updates use a persistent keystore on the server and can install over the current app.

Copy the APK off the host with your usual file transfer. Do not commit `mobile/android/app/google-services.json` or the FCM service-account JSON.

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
