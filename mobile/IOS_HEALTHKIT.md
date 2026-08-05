# UBETRA iOS shell (Capacitor) — Apple Health sleep

The Android Capacitor app already loads the PWA. **Apple HealthKit sleep sync requires an iOS target.**

## Status

- Backend: `POST /api/dynamics/{id}/sleep/apple/import` accepts `{ sessions: [{ start_at, end_at, external_id?, sleep_score?, stages?, notes? }] }`.
- Web UI calls `window.UbetraAppleHealth.exportSleepSessions({ days })` when present; otherwise shows that the iOS app is required.

## Add iOS (outline)

```bash
cd mobile
npx cap add ios
# Add a HealthKit plugin or native Swift bridge that:
# 1) requests HKSleepAnalysis permission
# 2) queries samples for the last N days
# 3) exposes results to JS as window.UbetraAppleHealth.exportSleepSessions
npx cap sync ios
```

Suggested JS bridge shape:

```js
window.UbetraAppleHealth = {
  async exportSleepSessions({ days = 14 } = {}) {
    // return [{ start_at: ISO, end_at: ISO, external_id, sleep_score? }]
  }
};
```

Enable HealthKit capability in Xcode and add usage description strings for sleep.

Until the iOS shell ships, partners can use **manual sleep logging** or **Google / Garmin** sync on Tracking → Sleep.
