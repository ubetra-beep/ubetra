# UBETRA Android APK (Capacitor)

Native shell for `com.ubetra.app`. The first launch asks for your self-hosted `https://…` URL, or you can continue phone-only. Firebase Cloud Messaging is used for background push when a server is configured. Call ringing / DND bypass is prepared via a dedicated `ubetra_calls` notification channel.

PWAs (Chrome/Edge) cannot reliably ignore Do Not Disturb or show full-screen incoming-call UI. This APK is the path for that.

## Prerequisites

On a machine with **Android Studio** (Java + Android SDK):

1. Node 20+
2. Android Studio Ladybug+ (SDK 35 recommended)
3. A free [Firebase](https://console.firebase.google.com/) project with **Cloud Messaging** enabled
4. This repo checked out

## One-time Firebase setup

1. Create a Firebase Android app whose package id is `com.ubetra.app` (`appId` in `capacitor.config.json`). The watch is a second app, `com.ubetra.wear`.
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
# → mobile/dist/ubetra.apk and, when release packaging succeeds, mobile/dist/ubetra.aab
# → mobile/dist/ubetra-wear.apk and ubetra-wear.aab when the SDK image can compile Wear
```

Wear only, without rebuilding the phone app:

```bash
bash mobile/scripts/build-apk.sh --wear-only
```

The SDK image ships Android platforms 33 and 34. The wear module compiles against platform 35, same as the phone app, and the script installs that platform plus build-tools 35 inside the container before Gradle.

The web app serves the phone file at **`/apk/ubetra.apk`** and, once `mobile/dist/ubetra-wear.apk` is on the server, the watch file at **`/apk/ubetra-wear.apk`**. In the Android app, **Settings → This device → Update app** downloads the phone APK with the system download manager.

## Install the phone APK

Close UBETRA completely, then open **`/apk/ubetra.apk`** (or the copy in `mobile/dist/`). Play Protect may warn (sideload) — tap **Install anyway**.

**“App not installed”:** the previous APKs were signed with a throwaway debug key. Uninstall the old UBETRA **once**, then install 0.82+. Later updates use a persistent keystore on the server and can install over the current app.

## Install the Wear APK

The watch app is a separate package, `com.ubetra.wear`. It cannot share the phone application id `com.ubetra.app`. Both artifacts are signed with the same upload keystore (`mobile/keystore/ubetra.jks`, alias `ubetra`). The password stays in `mobile/keystore/password` and is not committed. Play App Signing can hold the app signing key; this file is the upload key.

From a computer that can see the watch:

```bash
adb devices
adb -s <watch-serial> install -r mobile/dist/ubetra-wear.apk
```

The same file is published at **`/apk/ubetra-wear.apk`** when this server build is deployed. There is no watch-install button in the phone app. If Gradle cannot compile the module, the phone APK is still written and `mobile/dist/ubetra-wear.json` records `built: false` plus the log path `mobile/dist/ubetra-wear-build.log`.

## Connect a watch

The watch requires the phone. It does not ask for a server URL and it does not keep an account token.

1. On the phone, open Settings → Connect watch. The phone shows an 8-character code for about five minutes.
2. On the watch, open UBETRA and enter that code.
3. The phone creates an AES-GCM key and sends it once in the pair reply. Later messages are `version` + `nonce` + ciphertext. The watch stores the key in encrypted preferences.
4. Tiles and complications read the last summary the phone pushed. If the phone is not connected, actions say **Open phone**.
5. Add tiles from the watch tile picker: **Chastity**, **Quick lock**, **Quick log**. Add complications: **Lock status**, **Last night sleep**, **Cycle day**, **7-day orgasms**.

Unpair from the phone settings screen or from the watch. That drops the key on that side.

Copy the APK off the host with your usual file transfer. Do not commit `mobile/android/app/google-services.json` or the FCM service-account JSON.

## App behavior

- First launch: enter `https://your-ubetra.example`, or continue phone-only.
- Phone-only uses the bundled Today / Log / chastity UI and a SQLite log on the phone.
- When a server URL is saved but the server does not answer, the same log stays active and Chat, Play, video, vault, and assistant controls are greyed out.
- When the server answers, the phone pushes pending chastity and orgasm rows, then pulls. A newer `updated_at` wins. An unpushed local row is not deleted.
- `frontend/app.js` detects Capacitor and registers FCM via `POST /api/push/native` instead of Web Push when a server session exists.
- Server sends native tokens with FCM HTTP v1 **HIGH** priority on channel `ubetra_chat` (or `ubetra_calls` when `kind=call`).
- **Calls / DND:** after install, open Android Settings → Apps → UBETRA → **Do Not Disturb access** (Notification policy) → Allow. The `ubetra_calls` channel is created with `setBypassDnd(true)`.

## Change server URL

On the phone, Settings → Server. There is no baked-in host in `capacitor.config.json`.

## PWA vs APK

| | Chrome/Edge PWA | This APK |
|--|--|--|
| Install | Install app from browser | Play internal testing (AAB) |
| Background chat push | Best-effort (OEM battery) | Native FCM when a server is configured |
| Bypass DND for calls | No | Yes (with policy access) |
| Phone-only log | No | Yes |
| Watch | No | Encrypted relay through the phone |
| Full-screen incoming call | No | Planned on `ubetra_calls` |

Keep the PWA for desktop; use the APK on Android phones once Firebase is wired.
