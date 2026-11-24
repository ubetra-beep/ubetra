# Play Console checklist

This file is the publish checklist. Nothing here uploads a listing or an AAB.

Packages:

- Phone: `com.ubetra.app` → `mobile/dist/ubetra.aab`
- Watch: `com.ubetra.wear` → `mobile/dist/ubetra-wear.aab`

Version comes from `mobile/apk-version.json` (currently 0.92.0, version code 92). Rebuild with:

```bash
bash mobile/scripts/build-apk.sh
```

If `bundleRelease` fails, `mobile/dist/ubetra.json` or `mobile/dist/ubetra-wear.json` has `built: false` and the exact Gradle log path. The Gradle project is still the one to fix. Do not treat a missing AAB as uploaded.

## Upload key

`mobile/keystore/ubetra.jks`, alias `ubetra`, is the upload key. The password is in `mobile/keystore/password` on the build machine. Do not commit that file and do not paste it into Play Console notes.

In Play Console, enroll in **Play App Signing**. Upload the AAB with this keystore. Google holds the app signing key. If you later switch to a Play-generated upload key, register the new upload certificate in Play App Signing and stop using `ubetra.jks` for new uploads.

The phone and watch are different application ids. Play will ask for each of them. The same upload keystore can sign both.

## Steps

1. Create a Google Play developer account (one-time $25).
2. Create two apps: **UBETRA** (`com.ubetra.app`) and **UBETRA Wear** (`com.ubetra.wear`).
3. Host a public privacy policy. This repo serves a starter at `/privacy` (`frontend/privacy.html`). Put that URL on a public host before you fill the store listing, and replace the starter text with the policy you want to stand behind. The page should say the app is self-hosted, the phone keeps a local log, the watch has no account token, and there is no website-blocking VPN.
4. Data safety: account login when a server is configured; optional health-adjacent sleep and cycle if Health Connect is used; encrypted local storage for the phone log and the watch key; no website-blocking VPN and no Edge Guard.
5. Complete the content rating questionnaire. The app includes adult relationship tracking. Answer for the features you actually ship.
6. Internal testing: upload `ubetra.aab` and `ubetra-wear.aab`, then add testers by email. They install from Play. Sideload is not required for that track.
7. Wear form factor: declare the watch. `com.ubetra.wear` is not a standalone watch app (`com.google.android.wearable.standalone` is false). Point Play at `com.ubetra.app` as the companion phone app when it asks.
8. Store listing: screenshots, feature graphic, short description, and full description. Use the name UBETRA. Do not mention a personal hostname.

## What the builds contain

- Phone first launch asks for a self-hosted URL or continues phone-only.
- Phone SQLite is the logger when no server is set, and the backup when a server is configured but unreachable or behind pending local writes.
- Chat, Play, video, vault, and assistant stay grey until the server answers.
- The watch sends AES-GCM payloads to the phone. It does not call the server.

Out of scope: pressing Publish, and uploading from CI.
